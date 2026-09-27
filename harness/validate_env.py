#!/usr/bin/env python3
"""Box check: prove a built image is a trustworthy base before any task is built on it.

    identity     the image holds the code of the commit we asked for (a file from that
                 commit hashes the same inside the image as in git)
    no_history   no .git directory inside /app
    collection   pytest collects the chosen test targets without errors
    stability    the targets run --repeat times in fresh containers (`docker run --rm`,
                 nothing reused) and every test id gets the same outcome every time
    baseline     per-test outcomes are recorded; failures are listed, never hidden

Writes output/envs/<tag>.manifest.json.

Usage:
    python3 harness/validate_env.py --tag pretix-env:base --sha <sha> --targets tests/api/test_x.py
"""
import argparse
import hashlib
import json
import pathlib
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from build_env import DEFAULT_REPO, ROOT, lock_path

IDENTITY_FILE = "src/pretix/__init__.py"


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def docker(tag, script, mount=None):
    cmd = ["docker", "run", "--rm"]
    if mount:
        cmd += ["-v", f"{mount}:/w"]
    return sh(cmd + [tag, "bash", "-c", script])


def junit_outcomes(path):
    out = {}
    for case in ET.parse(path).getroot().iter("testcase"):
        tid = f"{case.get('classname')}::{case.get('name')}"
        tags = {c.tag for c in case}
        out[tid] = "skip" if "skipped" in tags else ("fail" if tags & {"failure", "error"} else "pass")
    return out


def validate(tag, sha, targets, repo=DEFAULT_REPO, env="pretix", repeat=3, workers=4):
    checks = {}
    want = hashlib.sha256(sh(["git", "-C", str(repo), "show", f"{sha}:{IDENTITY_FILE}"]).stdout.encode()).hexdigest()
    got = docker(tag, f"sha256sum /app/{IDENTITY_FILE} | cut -d' ' -f1").stdout.strip()
    checks["identity"] = want == got
    checks["no_history"] = docker(tag, "test ! -e /app/.git").returncode == 0

    paths = " ".join(targets)
    col = docker(tag, f"python -m pytest --collect-only -q -p no:cacheprovider {paths} 2>&1 | tail -3")
    checks["collection"] = bool(targets) and "error" not in col.stdout.lower() and "no tests ran" not in col.stdout
    collected = col.stdout.strip().splitlines()[-1] if col.stdout.strip() else ""

    runs = []
    with tempfile.TemporaryDirectory(dir=ROOT / "output" / "envs") as w:
        for i in range(repeat if checks["collection"] else 0):
            docker(tag, f"python -m pytest {paths} -p no:sugar -p no:cacheprovider -q -n {workers} "
                        f"--junitxml=/w/run{i}.xml >/w/run{i}.log 2>&1; true", mount=w)
            junit = pathlib.Path(w) / f"run{i}.xml"
            runs.append(junit_outcomes(junit) if junit.exists() else {})
    ids = set().union(*runs) if runs else set()
    unstable = sorted(t for t in ids if len({r.get(t, "missing") for r in runs}) > 1)
    checks["stability"] = bool(ids) and not unstable
    baseline = runs[0] if runs else {}

    lock = lock_path(env, sha)
    manifest = {
        "tag": tag,
        "image_id": sh(["docker", "image", "inspect", tag, "--format", "{{.Id}}"]).stdout.strip(),
        "platform": sh(["docker", "image", "inspect", tag, "--format", "{{.Os}}/{{.Architecture}}"]).stdout.strip(),
        "commit": sha,
        "lock": str(lock.relative_to(ROOT)),
        "lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest() if lock.exists() else None,
        "targets": targets, "repeat": repeat, "collected": collected,
        "checks": checks, "verdict": "ok" if all(checks.values()) else "bad",
        "baseline_counts": {k: sum(1 for v in baseline.values() if v == k) for k in ("pass", "fail", "skip")},
        "unstable": unstable,
        "baseline_failures": sorted(t for t, v in baseline.items() if v == "fail"),
    }
    out = ROOT / "output" / "envs" / (tag.replace(":", "_").replace("/", "_") + ".manifest.json")
    out.write_text(json.dumps(manifest, indent=2))
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--sha", required=True)
    ap.add_argument("--repo", default=str(DEFAULT_REPO))
    ap.add_argument("--env", default="pretix")
    ap.add_argument("--targets", nargs="+", required=True, help="test paths relative to /app/src")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    m = validate(args.tag, args.sha, args.targets, args.repo, args.env, args.repeat, args.workers)
    print(json.dumps({k: m[k] for k in ("verdict", "checks", "collected", "baseline_counts", "platform")}, indent=2))
    raise SystemExit(0 if m["verdict"] == "ok" else 1)


if __name__ == "__main__":
    main()
