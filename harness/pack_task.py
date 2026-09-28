#!/usr/bin/env python3
"""Pack a screened PR into a Harbor task folder.

Reads output/screens/pr<N>/ (from screen_pr.py) and writes tasks/<slug>/:

    instruction.md               DRAFT skeleton: the ticket is written by hand, never generated
    task.toml                    metadata, timeouts, resources, network policy
    environment/Dockerfile       pretix at the PR's parent commit, fetched by sha, no .git
    environment/requirements.lock
    solution/solve.sh            applies solution/gold.patch (the real PR's product change)
    solution/gold.patch
    tests/test.sh                restores graded test files, runs them, writes reward.json
    tests/grade.py               turns junit results into reward.json
    tests/must_turn_green.json   F2P ids (graded)
    tests/must_stay_green.json   P2P ids (graded)
    tests/files/<path>           the PR's versions of its test files, copied over /app at verify time

Usage:
    python3 harness/pack_task.py --pr 5666 --slug pretix-reusable-media-multi-link
"""
import argparse
import json
import re
import pathlib
import shutil
import stat
import subprocess
import tomllib

from build_env import DEFAULT_REPO, HARNESS, ROOT, ci_python, git, lock_path

TEMPLATES = HARNESS / "task_template"
TICKETS = HARNESS / "tickets"
SCREENS = ROOT / "output" / "screens"
TASKS = ROOT / "tasks"
UPSTREAM = "https://github.com/pretix/pretix.git"
TAMPER_PATTERN = r"_pytest|PYTEST_CURRENT_TEST|junitxml|pytest_runtest|TestReport"


def render(text, **values):
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


def make_executable(path):
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def pack(pr, slug, repo=DEFAULT_REPO, force=False, screen=None, prs=None, upstream=None):
    screen_dir = SCREENS / (screen or f"pr{pr}")
    screen = json.loads((screen_dir / "screen.json").read_text())
    if screen["verdict"] not in ("ok", "thin"):
        raise SystemExit(f"{screen_dir.name} verdict is {screen['verdict']}; only ok/thin screens are packed")
    sha, base = screen["sha"], screen["base"]
    out = TASKS / slug
    if out.exists():
        if not force:
            raise SystemExit(f"{out} exists (use --force to overwrite)")
        shutil.rmtree(out)
    for d in ("environment", "solution", "tests"):
        (out / d).mkdir(parents=True)

    images = json.loads((HARNESS / "env" / "pretix" / "python_images.json").read_text())
    py = ci_python(repo, base, images)
    shutil.copy(lock_path("pretix", base), out / "environment" / "requirements.lock")
    dockerfile = render((TEMPLATES / "Dockerfile").read_text(), PYTHON_IMAGE=images[py], UPSTREAM=UPSTREAM, BASE_SHA=base)
    if upstream:
        # Chain task: the base commit only exists locally. Fetch the real upstream commit it was derived
        # from and apply the feature-removal patch in the same layer, deleting the patch right away.
        removal = subprocess.run(["git", "-C", str(repo), "diff", "--binary", upstream, base],
                                 capture_output=True, check=True).stdout
        (out / "environment" / "feature_removal.patch").write_bytes(removal)
        dockerfile = dockerfile.replace(f"git fetch -q --depth 1 {UPSTREAM} {base}", f"git fetch -q --depth 1 {UPSTREAM} {upstream}")
        dockerfile = dockerfile.replace(
            "    git checkout -q FETCH_HEAD && \\\n    rm -rf /app/.git",
            "    git checkout -q FETCH_HEAD && \\\n    git apply --whitespace=nowarn /tmp/feature_removal.patch && \\\n"
            "    rm -rf /app/.git /tmp/feature_removal.patch")
        dockerfile = dockerfile.replace("RUN git init -q /app", "COPY feature_removal.patch /tmp/feature_removal.patch\nRUN git init -q /app")
    (out / "environment" / "Dockerfile").write_text(dockerfile)

    shutil.copy(screen_dir / "gold.patch", out / "solution" / "gold.patch")
    shutil.copy(TEMPLATES / "solve.sh", out / "solution" / "solve.sh")
    make_executable(out / "solution" / "solve.sh")

    # The verifier's own copy of the whole test tree and pytest config at the PR commit. test.sh
    # replaces /app/src/tests with it, so nothing the agent does to tests survives grading.
    tar = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar.gz", sha, "src/tests", "src/setup.cfg"],
                         capture_output=True, check=True).stdout
    (out / "tests" / "pristine.tar.gz").write_bytes(tar)
    # How often each product file already mentions pytest internals, so grading can flag new ones.
    tamper = {}
    for rev in (base, sha):
        hits = subprocess.run(["git", "-C", str(repo), "grep", "-c", "-E", TAMPER_PATTERN, rev, "--", "src/pretix"],
                              capture_output=True, text=True).stdout
        for line in hits.splitlines():  # "<rev>:<path>:<count>"
            location, count = line.rsplit(":", 1)
            path = location.split(":", 1)[1]
            tamper[path] = max(tamper.get(path, 0), int(count))
    (out / "tests" / "tamper_baseline.json").write_text(json.dumps(tamper, indent=2))
    graded_files = [t[len("src/"):] for t in screen["test_files"]]
    must_turn = [x["test"] for x in json.loads((screen_dir / "must_turn_green.json").read_text())]
    must_stay = json.loads((screen_dir / "must_stay_green.json").read_text())
    (out / "tests" / "must_turn_green.json").write_text(json.dumps(must_turn, indent=2))
    (out / "tests" / "must_stay_green.json").write_text(json.dumps(must_stay, indent=2))
    shutil.copy(TEMPLATES / "grade.py", out / "tests" / "grade.py")
    (out / "tests" / "test.sh").write_text(render(
        (TEMPLATES / "test.sh").read_text(), GRADED_FILES=" ".join(graded_files)))
    make_executable(out / "tests" / "test.sh")

    # Hand-written parts live in harness/tickets/ so re-packing never overwrites them.
    ticket = TICKETS / f"{slug}.md"
    notes = tomllib.loads((TICKETS / f"{slug}.toml").read_text()) if (TICKETS / f"{slug}.toml").exists() else {}
    toml_text = render((TEMPLATES / "task.toml").read_text(), SLUG=slug, N_TURN=len(must_turn), N_STAY=len(must_stay))
    for key in ("difficulty_explanation", "solution_explanation", "expert_time_estimate_hours"):
        if key in notes:
            value = notes[key] if isinstance(notes[key], (int, float)) else json.dumps(notes[key])
            toml_text = re.sub(rf'^{key} = .*$', f"{key} = {value}", toml_text, count=1, flags=re.M)
    (out / "task.toml").write_text(toml_text)
    (out / "instruction.md").write_text(ticket.read_text() if ticket.exists() else (TEMPLATES / "instruction.md").read_text())

    (out / ".pack.json").write_text(json.dumps({
        "pr": pr, "prs": prs or [pr], "sha": sha, "base": base, "python": py, "slug": slug,
        "must_turn_green": len(must_turn), "must_stay_green": len(must_stay),
        "gold_src_files": screen["src_files"],
    }, indent=2))
    print(f"packed {screen_dir.name} -> {out}  (python {py}, {len(must_turn)} must_turn_green, {len(must_stay)} must_stay_green)")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pr", type=int, help="single PR (screen output/screens/pr<N>)")
    ap.add_argument("--screen", help="screen directory name for a chain, e.g. chainA")
    ap.add_argument("--prs", type=int, nargs="*", help="member PRs of a chain (for leak checks)")
    ap.add_argument("--upstream", help="chain only: public commit the local base was derived from")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    pack(args.pr or (args.prs or [None])[-1], args.slug, force=args.force, screen=args.screen, prs=args.prs, upstream=args.upstream)


if __name__ == "__main__":
    main()
