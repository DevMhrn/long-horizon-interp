#!/usr/bin/env python3
"""Can a set of PRs be removed together from the commit of the newest one?

Reverse-applies each PR's product diff (newest first) on a scratch worktree at the newest PR's
commit, using 3-way merge. Migrations are reported separately (they are handled by removing the
PR's migration files and re-pointing later dependencies). Reports conflict files and hunks per PR.

Usage:  python3 harness/chain_check.py 5019 4962 [5565 ...]
"""
import pathlib, subprocess, sys, shutil
ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO = ROOT / "output" / "repos" / "pretix"
EXCLUDE = [":!doc", ":!src/pretix/base/migrations", ":!*.po", ":!*.mo", ":!src/pretix/static/jsi18n"]

def git(*a, cwd=REPO, check=True, **kw):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=check, **kw)

def sha(pr):
    return git("log", "--format=%H", f"--grep=(#{pr})", "-1").stdout.strip()

def main(prs):
    prs = sorted({int(p) for p in prs}, key=lambda p: git("log", "-1", "--format=%ct", sha(p)).stdout, reverse=True)
    top = sha(prs[0])
    wt = ROOT / "output" / f"chaincheck_{'_'.join(map(str, prs))}"
    shutil.rmtree(wt, ignore_errors=True)
    git("worktree", "add", "-q", "-f", "--detach", str(wt), top)
    rows = []
    try:
        for pr in prs:
            s = sha(pr)
            diff = git("diff", f"{s}^", s, "--", ".", *EXCLUDE).stdout
            ap = subprocess.run(["git", "apply", "-R", "--3way", "--whitespace=nowarn"], cwd=wt, input=diff,
                                capture_output=True, text=True)
            unmerged = [f for f in git("diff", "--name-only", "--diff-filter=U", cwd=wt).stdout.split() if f]
            hunks = sum((wt / f).read_text(errors="ignore").count("\n<<<<<<<") for f in unmerged if (wt / f).exists())
            failed = [l for l in ap.stderr.splitlines() if l.startswith("error:")]
            migs = git("diff", "--name-only", f"{s}^", s, "--", "src/pretix/base/migrations").stdout.split()
            rows.append((pr, unmerged, hunks, failed, migs))
            git("add", "-A", cwd=wt); git("-c", "user.email=x", "-c", "user.name=x", "commit", "-qm", f"r{pr}", cwd=wt, check=False)
    finally:
        git("worktree", "remove", "--force", str(wt), check=False)
    print(f"chain {prs} (removed from #{prs[0]}):")
    for pr, un, h, failed, migs in rows:
        print(f"  -#{pr}: conflict files {len(un)} {[pathlib.Path(u).name for u in un]}, hunks {h}, "
              f"hard failures {len(failed)}, migrations {len(migs)}")
        for f in failed[:3]:
            print("      ", f[:120])

if __name__ == "__main__":
    main(sys.argv[1:])
