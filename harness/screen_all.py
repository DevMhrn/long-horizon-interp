#!/usr/bin/env python3
"""Run every mined candidate through build -> box check -> behavior proof.

For each PR in output/mining/candidates.json:
    1. build     image of the PR's parent commit (Python + lock chosen for that commit)
    2. box       validate_env on the PR's test files that already exist at the parent
                 (identity, no .git, collection, one baseline run; stability of the graded
                 tests is proven by the repeated runs in step 3)
    3. behavior  screen_pr with --repeat runs before and after the gold patch

One PR failing never stops the batch; its stage and error are recorded instead.
Images of rejected PRs are removed afterwards unless --keep-images is set.

Outputs:
    output/screens/pr<N>/...          per-PR evidence (see screen_pr.py)
    output/screens/summary.json|.md   one row per PR

Usage:
    python3 harness/screen_all.py [--only 5666 6115] [--parallel 2] [--repeat 3]
"""
import argparse
import concurrent.futures as cf
import json
import pathlib
import subprocess
import time
import traceback

from build_env import DEFAULT_REPO, ROOT, build, git
from screen_pr import screen, split_patches
from validate_env import validate

SCREENS = ROOT / "output" / "screens"
SMOKE_TARGET = "tests/base/test_orders.py"


def exists_at(repo, sha, path):
    return subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{sha}:{path}"],
                          capture_output=True).returncode == 0


def process(c, repeat, workers, keep_images, rebuild):
    pr, sha = c["pr"], c["sha"]
    tag = f"pretix-env:pr{pr}-base"
    out = SCREENS / f"pr{pr}"
    row = {"pr": pr, "date": c["date"], "title": c["title"], "sha": sha[:10], "stage": "build"}
    t0 = time.time()
    try:
        base, runnable, *_ = split_patches(DEFAULT_REPO, sha)
        row["base"] = base[:10]
        have = subprocess.run(["docker", "image", "inspect", tag], capture_output=True).returncode == 0
        if rebuild or not have:
            info = build("pretix", DEFAULT_REPO, base, tag)
            row["python"] = info["python"]

        row["stage"] = "box"
        targets = [t[len("src/"):] for t in runnable if exists_at(DEFAULT_REPO, base, t)] or [SMOKE_TARGET]
        box = validate(tag, base, targets, repeat=1, workers=workers)
        row["box"] = box["verdict"]
        row["box_checks"] = box["checks"]
        row["baseline_failures"] = len(box["baseline_failures"])
        if box["verdict"] != "ok":
            row["verdict"] = "bad:box_check_failed"
            return row

        row["stage"] = "behavior"
        res = screen(sha, tag, out, repeat=repeat, workers=workers)
        row["verdict"] = res["verdict"]
        row["counts"] = res.get("counts", {})
        row["why_red_before"] = res.get("why_red_before", {})
        row["stage"] = "done"
    except Exception as e:  # recorded, never fatal to the batch
        row["verdict"] = f"error:{row['stage']}"
        row["error"] = f"{type(e).__name__}: {str(e)[-1500:]}"
        out.mkdir(parents=True, exist_ok=True)
        (out / "error.txt").write_text(traceback.format_exc())
    finally:
        row["minutes"] = round((time.time() - t0) / 60, 1)
        accepted = row.get("verdict") in ("ok", "thin")
        if not keep_images and not accepted:
            subprocess.run(["docker", "rmi", "-f", tag], capture_output=True)
        print(f"[#{pr}] {row.get('verdict')}  {row.get('counts', '')}  ({row['minutes']} min)", flush=True)
    return row


def write_summary(rows):
    existing = {}
    if (SCREENS / "summary.json").exists():
        existing = {r["pr"]: r for r in json.loads((SCREENS / "summary.json").read_text())}
    existing.update({r["pr"]: r for r in rows})
    rows = sorted(existing.values(), key=lambda r: r["date"], reverse=True)
    (SCREENS / "summary.json").write_text(json.dumps(rows, indent=2))
    lines = ["| PR | Merged | Verdict | must_turn_green | must_stay_green | broken_by_gold | flaky | red before because | Title |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        k = r.get("counts", {})
        why = ", ".join(f"{a} {b}" for a, b in sorted(r.get("why_red_before", {}).items()))
        lines.append(f"| #{r['pr']} | {r['date']} | {r.get('verdict')} | {k.get('must_turn_green', '')} | "
                     f"{k.get('must_stay_green', '')} | {k.get('broken_by_gold', '')} | {k.get('flaky', '')} | "
                     f"{why} | {r['title'][:60]} |")
    (SCREENS / "summary.md").write_text("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default=str(ROOT / "output" / "mining" / "candidates.json"))
    ap.add_argument("--only", nargs="*", type=int)
    ap.add_argument("--parallel", type=int, default=2)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--keep-images", action="store_true")
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()

    cands = json.loads(pathlib.Path(args.candidates).read_text())["candidates"]
    if args.only:
        cands = [c for c in cands if c["pr"] in args.only]
    SCREENS.mkdir(parents=True, exist_ok=True)
    git(DEFAULT_REPO, "rev-parse", "HEAD")  # fail fast if the clone is missing

    rows = []
    with cf.ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = [pool.submit(process, c, args.repeat, args.workers, args.keep_images, args.rebuild) for c in cands]
        for f in cf.as_completed(futures):
            rows.append(f.result())
            write_summary(rows)
    print((SCREENS / "summary.md").read_text())


if __name__ == "__main__":
    main()
