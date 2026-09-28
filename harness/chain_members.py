#!/usr/bin/env python3
"""Does every PR in a chain own part of the exam?

For each must_turn_green test of a chain screen, find which member PR added or changed that test
function (by comparing the function's source before/after each member). Tests no member touched
(e.g. old tests that fail only because a shared import/fixture changed) are "carried".

Rules for a valid chain:
    at least 4 must_turn_green tests in total
    every member owns at least 2
    no member owns 90% or more

Usage:  python3 harness/chain_members.py output/screens/chainA 4962 5565 5019
"""
import ast
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO = ROOT / "output" / "repos" / "pretix"


def git(*a):
    return subprocess.run(["git", "-C", str(REPO), *a], capture_output=True, text=True).stdout


def functions(src):
    out = {}
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for f in node.body:
                if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out[f"{node.name}::{f.name}"] = ast.get_source_segment(src, f)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.setdefault(node.name, ast.get_source_segment(src, node))
    return out


def touched_by(pr):
    s = git("log", "--format=%H", f"--grep=(#{pr})", "-1").strip()
    touched = set()
    for f in git("diff", "--name-only", f"{s}^", s, "--", "src/tests").split():
        if not f.endswith(".py"):
            continue
        module = ".".join(pathlib.PurePath(f).relative_to("src").with_suffix("").parts)
        before, after = functions(git("show", f"{s}^:{f}")), functions(git("show", f"{s}:{f}"))
        for name, code in after.items():
            if before.get(name) != code:
                touched.add(f"{module}::{name.split('::')[-1]}")
                touched.add(f"{module}.{name.split('::')[0]}::{name.split('::')[-1]}" if "::" in name else "")
    return touched - {""}


def main():
    screen_dir, *prs = sys.argv[1:]
    must_turn = [x["test"] for x in json.loads((pathlib.Path(screen_dir) / "must_turn_green.json").read_text())]
    owners = {int(p): touched_by(p) for p in prs}
    owned = {p: [] for p in owners}
    carried = []
    for tid in must_turn:
        base = tid.split("[")[0]
        hits = [p for p, t in owners.items() if base in t]
        # attribute to the latest member that touched it (members listed oldest -> newest)
        (owned[hits[-1]].append(tid) if hits else carried.append(tid))
    total = len(must_turn)
    shares = {p: len(v) for p, v in owned.items()}
    biggest = max(shares.values()) if shares else 0
    checks = {
        "at_least_4_total": total >= 4,
        "every_member_owns_2": all(v >= 2 for v in shares.values()),
        "no_member_owns_90pct": biggest < 0.9 * total,
    }
    report = {"total_must_turn_green": total, "owned": shares, "carried_by_shared_changes": len(carried),
              "checks": checks, "ok": all(checks.values()),
              "detail": {str(p): v for p, v in owned.items()}, "carried": carried}
    (pathlib.Path(screen_dir) / "members.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: report[k] for k in ("total_must_turn_green", "owned", "carried_by_shared_changes", "checks", "ok")}, indent=2))


if __name__ == "__main__":
    main()
