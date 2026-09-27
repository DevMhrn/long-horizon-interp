#!/usr/bin/env python3
"""Build a Docker image of a repo frozen at one commit.

    1. `git archive <sha>` -> repo.tar            (no .git, so no history to mine)
    2. pick the Python image from the commit's own CI (the version it tests SQLite on)
    3. use the commit's lock: harness/env/<env>/locks/<sha12>.lock
       If there is none yet, bootstrap it: install unlocked but resolved as of the
       commit date (`uv --exclude-newer`), freeze that working container, then
       rebuild from the lock. Pins always come from a container that really installed.
    4. docker build

Build contexts go to output/envs/<tag>/ (git- and docker-ignored).

Usage:
    python3 harness/build_env.py --sha <sha> --tag pretix-env:base
"""
import argparse
import json
import pathlib
import re
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "harness"
DEFAULT_REPO = ROOT / "output" / "repos" / "pretix"

LOCKED_DEPS = "RUN uv pip install --system --no-cache -r /tmp/requirements.lock"
LOCKED_PROJECT = "RUN PRETIX_DOCKER_BUILD=1 uv pip install --system --no-cache --no-deps -e ."


def run(cmd, **kw):
    print("+", " ".join(map(str, cmd)), flush=True)
    return subprocess.run(cmd, check=True, **kw)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def ci_python(repo, sha, available):
    """Lowest Python version the commit's CI runs the SQLite test job on."""
    wf = git(repo, "show", f"{sha}:.github/workflows/tests.yml")
    matrix = re.search(r"python-version:\s*\[([^\]]+)\]", wf)
    versions = [v.strip().strip("\"'") for v in matrix.group(1).split(",")] if matrix else []
    excluded = set(re.findall(r"database:\s*sqlite\s*\n\s*python-version:\s*[\"']?([\d.]+)", wf))
    sqlite_versions = [v for v in versions if v not in excluded and v in available]
    if not sqlite_versions:
        raise SystemExit(f"no pinned Python image for CI versions {versions} (excluded {excluded})")
    return sorted(sqlite_versions, key=lambda v: tuple(map(int, v.split("."))))[0]


def lock_path(env, sha):
    return HARNESS / "env" / env / "locks" / f"{sha[:12]}.lock"


def override_path(env, sha):
    """Optional per-commit resolver override, only for documented upstream breakage (e.g. yanked releases)."""
    return HARNESS / "env" / env / "overrides" / f"{sha[:12]}.txt"


def assemble(env, repo, sha, context, unlocked_as_of=None):
    context = pathlib.Path(context)
    if context.exists():
        shutil.rmtree(context)
    context.mkdir(parents=True)
    run(["git", "-C", str(repo), "archive", "--format=tar", "-o", str(context.resolve() / "repo.tar"), sha])
    dockerfile = (HARNESS / "env" / env / "Dockerfile").read_text()
    if unlocked_as_of:
        override = override_path(env, sha)
        flag = ""
        if override.exists():
            shutil.copy(override, context / "overrides.txt")
            dockerfile = dockerfile.replace("COPY requirements.lock /tmp/requirements.lock",
                                            "COPY requirements.lock /tmp/requirements.lock\nCOPY overrides.txt /tmp/overrides.txt")
            # The date cutoff would hide the fix release, so lift it for the overridden packages only;
            # the override itself pins the exact version.
            names = [re.split(r"[=<>!~ ]", l.strip())[0] for l in override.read_text().splitlines()
                     if l.strip() and not l.startswith("#")]
            flag = "--override /tmp/overrides.txt " + "".join(
                f"--exclude-newer-package {n}=2100-01-01T00:00:00Z " for n in names)
        dockerfile = dockerfile.replace(LOCKED_DEPS, "RUN true").replace(
            LOCKED_PROJECT,
            f'RUN PRETIX_DOCKER_BUILD=1 uv pip install --system --no-cache --exclude-newer {unlocked_as_of} {flag}-e ".[dev]"')
        (context / "requirements.lock").write_text("")
    else:
        shutil.copy(lock_path(env, sha), context / "requirements.lock")
    (context / "Dockerfile").write_text(dockerfile)
    return context


def build(env, repo, sha, tag, platform=None):
    images = json.loads((HARNESS / "env" / env / "python_images.json").read_text())
    py = ci_python(repo, sha, images)
    lock = lock_path(env, sha)
    if not lock.exists() or not lock.read_text().strip():
        as_of = git(repo, "log", "-1", "--format=%cI", sha).strip()
        _docker_build(env, repo, sha, tag + "-unlocked", images[py], platform, unlocked_as_of=as_of)
        out = subprocess.run(["docker", "run", "--rm", tag + "-unlocked", "uv", "pip", "freeze", "--system",
                              "--exclude-editable"], check=True, capture_output=True, text=True).stdout
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(out)
        subprocess.run(["docker", "rmi", "-f", tag + "-unlocked"], capture_output=True)
        print(f"wrote {lock} ({len(out.splitlines())} pins, resolved as of {as_of})")
    _docker_build(env, repo, sha, tag, images[py], platform)
    return {"python": py, "python_image": images[py], "lock": str(lock.relative_to(ROOT))}


def _docker_build(env, repo, sha, tag, python_image, platform, unlocked_as_of=None):
    context = ROOT / "output" / "envs" / tag.replace(":", "_").replace("/", "_")
    assemble(env, repo, sha, context, unlocked_as_of)
    cmd = ["docker", "build", "-q", "-t", tag, "--build-arg", f"PYTHON_IMAGE={python_image}"]
    if platform:
        cmd += ["--platform", platform]
    run(cmd + [str(context)], stdout=subprocess.DEVNULL)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="pretix", help="subdirectory of harness/env/")
    ap.add_argument("--repo", default=str(DEFAULT_REPO))
    ap.add_argument("--sha", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--platform", default=None, help="e.g. linux/amd64 (default: host platform)")
    args = ap.parse_args()
    sha = git(args.repo, "rev-parse", args.sha).strip()
    info = build(args.env, args.repo, sha, args.tag, args.platform)
    print(f"built {args.tag} from {sha} on Python {info['python']}")


if __name__ == "__main__":
    main()
