#!/usr/bin/env python3
"""Mine a repo's squash-merged PRs for feature-reconstruction candidates.

pretix squash-merges every PR, so each commit on master whose title ends in
"(#1234)" is exactly one PR. For each one we measure how much product code
and how much test code it touches, drop things that are not features, and
group the survivors into "families" of PRs that edit the same files, which
are the raw material for multi-PR tasks later.

Usage:
    python3 harness/mine_prs.py --repo output/repos/pretix --since 2025-06-01 \
        --out output/mining/candidates.json
"""
import argparse
import collections
import json
import re
import subprocess

PR_RE = re.compile(r"\(#(\d+)\)\s*$")
NOT_A_FEATURE = re.compile(r"^(fix|hotfix|translations?|bump|update|typo|revert|docs?\b|release|version)", re.I)
SRC_PREFIX = "src/pretix/"
TEST_PREFIX = "src/tests/"
SRC_EXT = (".py", ".html", ".js")
IGNORED_SRC = ("/locale/", "/static/")


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True).stdout


def parse_log(repo, since):
    out = git(repo, "log", f"--since={since}", "--no-merges", "--format=@@%H\t%ad\t%s", "--date=short", "--numstat")
    commits, cur = [], None
    for line in out.splitlines():
        if line.startswith("@@"):
            sha, date, title = line[2:].split("\t", 2)
            cur = {"sha": sha, "date": date, "title": title, "files": []}
            commits.append(cur)
        elif line.strip() and cur is not None:
            added, deleted, path = line.split("\t", 2)
            if added == "-":  # binary
                continue
            cur["files"].append((path, int(added), int(deleted)))
    return commits


def classify(commit):
    src, tests, migrations = [], [], []
    src_churn = test_added = 0
    for path, a, d in commit["files"]:
        if path.startswith(TEST_PREFIX):
            tests.append(path)
            test_added += a
        elif path.startswith(SRC_PREFIX) and "/migrations/" in path:
            migrations.append(path)
        elif path.startswith(SRC_PREFIX) and path.endswith(SRC_EXT) and not any(x in path for x in IGNORED_SRC):
            src.append(path)
            src_churn += a + d
    return src, tests, migrations, src_churn, test_added


def area(path):
    parts = path.split("/")
    return "/".join(parts[1:4])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--since", default="2025-06-01")
    ap.add_argument("--min-src-churn", type=int, default=120)
    ap.add_argument("--max-src-churn", type=int, default=2500)
    ap.add_argument("--min-src-files", type=int, default=3)
    ap.add_argument("--min-test-added", type=int, default=60)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    candidates, rejected = [], collections.Counter()
    for c in parse_log(args.repo, args.since):
        m = PR_RE.search(c["title"])
        if not m:
            rejected["not_a_pr"] += 1
            continue
        if NOT_A_FEATURE.match(c["title"]):
            rejected["not_a_feature"] += 1
            continue
        src, tests, migrations, churn, test_added = classify(c)
        if not tests:
            rejected["no_tests"] += 1
        elif test_added < args.min_test_added:
            rejected["too_few_test_lines"] += 1
        elif len(src) < args.min_src_files:
            rejected["too_few_src_files"] += 1
        elif not args.min_src_churn <= churn <= args.max_src_churn:
            rejected["src_size_out_of_range"] += 1
        else:
            candidates.append({
                "pr": int(m.group(1)),
                "sha": c["sha"],
                "date": c["date"],
                "title": c["title"],
                "src_files": src,
                "test_files": tests,
                "migrations": migrations,
                "src_churn": churn,
                "test_lines_added": test_added,
                "areas": [a for a, _ in collections.Counter(map(area, src)).most_common(3)],
            })

    # Families: PRs that share at least two product files are likely to build on each other.
    by_pr = {c["pr"]: set(c["src_files"]) for c in candidates}
    families = []
    for c in sorted(candidates, key=lambda c: c["date"]):
        related = [o["pr"] for o in candidates
                   if o["pr"] != c["pr"] and o["date"] >= c["date"] and len(by_pr[c["pr"]] & by_pr[o["pr"]]) >= 2]
        if related:
            families.append({"root": c["pr"], "later_related": related})

    result = {"repo": args.repo, "since": args.since, "rejected": dict(rejected),
              "n_candidates": len(candidates), "candidates": candidates, "families": families}
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)
    print(f"{len(candidates)} candidates, rejected: {dict(rejected)}")
    for c in sorted(candidates, key=lambda c: c["date"], reverse=True):
        print(f"  #{c['pr']:<5} {c['date']}  src={c['src_churn']:<5} files={len(c['src_files']):<3} "
              f"tests+={c['test_lines_added']:<5} {c['title'][:70]}")
    print(f"{len(families)} families (PRs sharing >=2 product files with a later PR)")


if __name__ == "__main__":
    main()
