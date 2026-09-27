#!/usr/bin/env python3
"""Behavior proof for one PR: which tests does it really turn green, and why were they red?

For a squash commit S with parent B:
    gold.patch  = diff B..S of product files     (what the agent must rebuild)
    tests.patch = diff B..S of test files        (what the verifier will run)

Inside the frozen image of B, the PR's test files run in fresh containers:
    before: B + tests.patch                 (repeated --repeat times)
    after:  B + tests.patch + gold.patch    (repeated --repeat times)

Every test id lands in exactly one bucket:
    must_turn_green   red before, green after, every run    (F2P, graded)
    must_stay_green   green before and after, every run     (P2P, graded)
    broken_by_gold    green before, red after                (gold breaks something -> reject)
    excluded          red after for other reasons            (never graded)
    flaky             outcome changed between repeats        (never graded)

For every must_turn_green test we also record WHY it was red before, so we know the task
fails for the right reason (the feature is missing) and not because of the environment.

Outputs in <out_dir>/:
    screen.json  must_turn_green.json  must_stay_green.json  gold.patch  tests.patch  logs/

Usage:
    python3 harness/screen_pr.py --sha <squash sha> --image pretix-env:<tag> --out output/screens/pr<N>
"""
import argparse
import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_REPO = ROOT / "output" / "repos" / "pretix"
TEST_PREFIX = "src/tests/"
# Browser end-to-end tests need Playwright + browsers; the repo's CI runs them in a separate job
# and excludes them from the main test run, so they are never part of a screen.
IGNORED_TESTS = ("src/tests/e2e/",)
DEPENDENCY_FILES = ("pyproject.toml", "setup.py", "setup.cfg", "requirements")
MIN_MUST_TURN_GREEN = 5

REASONS = [
    ("infra", re.compile(r"ConnectionError|ConnectionRefused|TimeoutError|Temporary failure in name resolution|"
                         r"OSError: \[Errno|No space left|Worker .* crashed", re.I)),
    ("missing_feature", re.compile(r"ImportError|ModuleNotFoundError|AttributeError|FieldError|FieldDoesNotExist|"
                                   r"NoReverseMatch|no such column|no such table|unexpected keyword argument|"
                                   r"KeyError|TypeError|NameError|LookupError|ValidationError|ValueError: .* is not a valid|"
                                   r"HttpResponseNotFound|"
                                   r"assert (404|405) ==|status_code == 20\d", re.I)),
    ("behavioral", re.compile(r"AssertionError|assert ", re.I)),
]


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def split_patches(repo, sha):
    base = git(repo, "rev-parse", f"{sha}^").strip()
    status = [line.split("\t") for line in git(repo, "diff", "--name-status", base, sha).splitlines()]
    files = [parts[-1] for parts in status]
    test_files = [f for f in files if f.startswith(TEST_PREFIX)]
    src_files = [f for f in files if not f.startswith(TEST_PREFIX) and not f.startswith("doc/")]
    deleted = {parts[-1] for parts in status if parts[0].startswith("D")}
    tests_patch = git(repo, "diff", "--binary", base, sha, "--", *test_files) if test_files else ""
    gold_patch = git(repo, "diff", "--binary", base, sha, "--", *src_files) if src_files else ""
    runnable = [t for t in test_files
                if t not in deleted and not t.startswith(IGNORED_TESTS) and t.endswith(".py") and pathlib.PurePath(t).name.startswith("test_")]
    return base, runnable, src_files, tests_patch, gold_patch


def added_dependencies(repo, sha, src_files):
    """Package specs the PR adds or changes. Removing a dependency is harmless: the frozen lock
    still contains it, and the after-run proves the code works without anything new."""
    dep_files = [f for f in src_files if pathlib.PurePath(f).name.startswith(DEPENDENCY_FILES)]
    if not dep_files:
        return []
    diff = git(repo, "diff", f"{sha}^", sha, "--", *dep_files)
    spec = re.compile(r'^\+\s*"?[A-Za-z0-9_.\-\[\]]+\s*(==|>=|<=|~=|!=|>|<)')
    return [line[1:].strip() for line in diff.splitlines() if spec.match(line) and not line.startswith("+++")]


class SuiteDoesNotLoad(RuntimeError):
    """Shared test helpers import the new feature, so NO test can run before it exists and
    must_stay_green cannot be measured. Such a PR cannot be graded fairly on its own."""


def run_stage(image, workdir, targets, with_gold, workers, label):
    apply = "git apply --whitespace=nowarn /w/tests.patch"
    if with_gold:
        apply += " && git apply --whitespace=nowarn /w/gold.patch"
    paths = " ".join(t[len("src/"):] for t in targets)
    script = (f"set -e; cd /app; {apply}; cd /app/src; "
              f"python -m pytest {paths} -p no:sugar -p no:cacheprovider -q -n {workers} "
              f"--junitxml=/w/{label}.xml >/w/{label}.log 2>&1 || true")
    proc = subprocess.run(["docker", "run", "--rm", "-v", f"{workdir}:/w", image, "bash", "-c", script],
                          capture_output=True, text=True)
    junit = pathlib.Path(workdir) / f"{label}.xml"
    if proc.returncode != 0 or not junit.exists():
        log = pathlib.Path(workdir) / f"{label}.log"
        tail = (log.read_text()[-2000:] if log.exists() else "") + proc.stderr[-2000:]
        if not with_gold and re.search(r"ImportError while loading conftest|Interrupted: \d+ errors? during collection", tail):
            raise SuiteDoesNotLoad(f"{label}: the whole test session fails to load without the feature\n{tail}")
        raise RuntimeError(f"{label}: patch apply or pytest failed to run\n{tail}")
    results = {}
    for case in ET.parse(junit).getroot().iter("testcase"):
        tid = f"{case.get('classname')}::{case.get('name')}"
        problem = next((c for c in case if c.tag in ("failure", "error")), None)
        skipped = any(c.tag == "skipped" for c in case)
        if skipped:
            results[tid] = ("skip", "")
        elif problem is not None:
            results[tid] = ("fail", ((problem.get("message") or "") + "\n" + (problem.text or ""))[:4000])
        else:
            results[tid] = ("pass", "")
    return results


def reason(message):
    if message is None:
        return "not_collected"  # the test file could not even import: the feature's API is missing
    for name, pattern in REASONS:
        if pattern.search(message):
            return name
    return "other"


def classify(before, after):
    ids = sorted(set().union(*before, *after))
    buckets = {k: [] for k in ("must_turn_green", "must_stay_green", "broken_by_gold", "excluded", "flaky")}
    why_red = {}
    for tid in ids:
        b = {r[tid][0] if tid in r else "fail" for r in before}
        a = {r[tid][0] if tid in r else "fail" for r in after}
        if len(b) > 1 or len(a) > 1:
            buckets["flaky"].append(tid)
        elif a == {"pass"} and b == {"fail"}:
            buckets["must_turn_green"].append(tid)
            why_red[tid] = reason(before[0][tid][1] if tid in before[0] else None)
        elif a == {"pass"} and b == {"pass"}:
            buckets["must_stay_green"].append(tid)
        elif b == {"pass"} and a == {"fail"}:
            buckets["broken_by_gold"].append(tid)
        else:
            buckets["excluded"].append(tid)
    return buckets, why_red


def verdict_for(buckets, why_red, touches_deps):
    reasons = set(why_red.values())
    if not buckets["must_turn_green"]:
        return "bad:no_must_turn_green"
    if buckets["broken_by_gold"]:
        return "bad:gold_breaks_tests"
    if "infra" in reasons:
        return "bad:red_for_infra_reasons"
    if touches_deps:
        return "bad:needs_dependency_change"
    if len(buckets["must_turn_green"]) < MIN_MUST_TURN_GREEN:
        return "thin"
    return "ok"


def screen(sha, image, out_dir, repo=DEFAULT_REPO, repeat=3, workers=4):
    base, runnable, src_files, tests_patch, gold_patch = split_patches(repo, sha)
    out = pathlib.Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    (out / "logs").mkdir(parents=True)
    (out / "gold.patch").write_text(gold_patch)
    (out / "tests.patch").write_text(tests_patch)
    if not runnable or not gold_patch:
        result = {"sha": sha, "base": base, "verdict": "bad:no_runnable_tests_or_no_source"}
        (out / "screen.json").write_text(json.dumps(result, indent=2))
        return result

    with tempfile.TemporaryDirectory(prefix="screen_", dir=out) as w:
        shutil.copy(out / "gold.patch", w)
        shutil.copy(out / "tests.patch", w)
        try:
            before = [run_stage(image, w, runnable, False, workers, f"before{i}") for i in range(repeat)]
        except SuiteDoesNotLoad as e:
            result = {"sha": sha, "base": base, "verdict": "bad:suite_does_not_load_before", "detail": str(e)[-1500:]}
            (out / "screen.json").write_text(json.dumps(result, indent=2))
            return result
        after = [run_stage(image, w, runnable, True, workers, f"after{i}") for i in range(repeat)]
        for f in pathlib.Path(w).glob("*.log"):
            shutil.copy(f, out / "logs" / f.name)

    buckets, why_red = classify(before, after)
    touches_deps = bool(added_dependencies(repo, sha, src_files))
    reason_counts = {}
    for r in why_red.values():
        reason_counts[r] = reason_counts.get(r, 0) + 1
    result = {
        "sha": sha, "base": base, "image": image, "repeat": repeat,
        "verdict": verdict_for(buckets, why_red, touches_deps),
        "test_files": runnable, "src_files": src_files, "touches_dependencies": touches_deps,
        "counts": {k: len(v) for k, v in buckets.items()},
        "why_red_before": reason_counts,
        **{k: v for k, v in buckets.items() if k not in ("must_turn_green", "must_stay_green")},
    }
    (out / "must_turn_green.json").write_text(json.dumps(
        [{"test": t, "red_before_because": why_red[t]} for t in buckets["must_turn_green"]], indent=2))
    (out / "must_stay_green.json").write_text(json.dumps(buckets["must_stay_green"], indent=2))
    (out / "screen.json").write_text(json.dumps(result, indent=2))
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(DEFAULT_REPO))
    ap.add_argument("--sha", required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--out", required=True, help="output directory, e.g. output/screens/pr5666")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    result = screen(args.sha, args.image, args.out, args.repo, args.repeat, args.workers)
    print(json.dumps({k: result.get(k) for k in ("verdict", "counts", "why_red_before")}, indent=2))


if __name__ == "__main__":
    main()
