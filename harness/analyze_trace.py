#!/usr/bin/env python3
"""Turn one agent trial into a failure analysis.

Reads the raw agent event stream (Codex JSONL today; Claude Code stream-json is detected too)
plus the verifier's details.json, and reports:

    timeline      what the agent did, in order (condensed)
    commands      grouped: explore (search/read), run_tests (which files), migrations, self-review, other
    files         product files the agent changed, grouped by layer
    verification  did it run the graded test files? the full suite? did the last test run pass?
    final_claim   the agent's last message (what it says it did)
    vs_reality    verifier result per ticket requirement (harness/tickets/<slug>.map.json)

Usage:
    python3 harness/analyze_trace.py output/runs/<slug>/<job>/<trial>
Writes <trial>/analysis.json and <trial>/analysis.md.
"""
import collections
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

EXPLORE = re.compile(r"\b(rg|grep|find|ls|cat|sed -n|head|tail|nl|wc|git (grep|log|show))\b")
TESTS = re.compile(r"\b(pytest|py\.test|manage\.py test)\b")
MIGRATE = re.compile(r"makemigrations|migrate\b")
REVIEW = re.compile(r"\bgit (diff|status)\b")


def events(trial):
    f = trial / "agent" / "codex.txt"
    if f.exists():
        for line in f.read_text(errors="ignore").splitlines():
            try:
                yield "codex", json.loads(line)
            except json.JSONDecodeError:
                continue
        return
    f = trial / "agent" / "claude-code.txt"
    if f.exists():
        for line in f.read_text(errors="ignore").splitlines():
            try:
                yield "claude", json.loads(line)
            except json.JSONDecodeError:
                continue


def normalize(trial):
    """-> list of {kind: message|command|edit, ...} in order."""
    out = []
    for fmt, e in events(trial):
        if fmt == "codex" and e.get("type") == "item.completed":
            it = e["item"]
            if it["type"] == "agent_message":
                out.append({"kind": "message", "text": it.get("text", "")})
            elif it["type"] == "command_execution":
                cmd = it.get("command", "")
                cmd = re.sub(r"^/bin/(ba)?sh -lc ", "", cmd).strip("'\"")
                out.append({"kind": "command", "cmd": cmd, "exit": it.get("exit_code"),
                            "output": it.get("aggregated_output", "")})
            elif it["type"] == "file_change":
                out.append({"kind": "edit", "paths": [c["path"] for c in it.get("changes", [])]})
        elif fmt == "claude" and e.get("type") == "result" and e.get("result"):
            out.append({"kind": "message", "text": e["result"]})
        elif fmt == "claude" and e.get("type") == "assistant":
            for block in e.get("message", {}).get("content", []):
                if block.get("type") == "text":
                    out.append({"kind": "message", "text": block["text"]})
                elif block.get("type") == "tool_use":
                    inp = block.get("input", {})
                    if block["name"] == "Bash":
                        out.append({"kind": "command", "cmd": inp.get("command", ""), "exit": None, "output": ""})
                    elif block["name"] in ("Edit", "Write", "MultiEdit"):
                        out.append({"kind": "edit", "paths": [inp.get("file_path", "")]})
    return out


def layer(path):
    p = path.replace("/app/", "")
    for key, name in (("/migrations/", "migrations"), ("/api/", "api"), ("/services/", "services"),
                      ("/models/", "models"), ("/control/", "control (admin UI)"), ("settings.py", "settings"),
                      ("src/tests/", "tests"), ("/base/", "base (other)")):
        if key in p:
            return name
    return "other"


def pytest_summary(output):
    m = re.findall(r"(\d+) (passed|failed|error|errors|skipped)", output)
    return {k: int(v) for v, k in m} if m else None


def analyze(trial):
    trial = pathlib.Path(trial).resolve()
    steps = normalize(trial)
    cmds = [s for s in steps if s["kind"] == "command"]
    groups = collections.Counter()
    test_runs = []
    for c in cmds:
        if TESTS.search(c["cmd"]):
            groups["run_tests"] += 1
            test_runs.append({"cmd": c["cmd"][:200], "result": pytest_summary(c["output"][-3000:])})
        elif MIGRATE.search(c["cmd"]):
            groups["migrations"] += 1
        elif REVIEW.search(c["cmd"]):
            groups["self_review"] += 1
        elif EXPLORE.search(c["cmd"]):
            groups["explore"] += 1
        else:
            groups["other"] += 1
    edited = sorted({p for s in steps if s["kind"] == "edit" for p in s["paths"]})
    by_layer = collections.defaultdict(list)
    for p in edited:
        by_layer[layer(p)].append(p.replace("/app/", ""))

    slug = trial.parent.parent.name
    graded_files = []
    task_dir = ROOT / "tasks" / slug
    if (task_dir / "tests" / "test.sh").exists():
        m = re.search(r"-c /app/src/setup\.cfg (.*?) -p no:sugar", (task_dir / "tests" / "test.sh").read_text())
        graded_files = m.group(1).split() if m else []
    ran = " ".join(t["cmd"] for t in test_runs)
    verification = {
        "test_runs": len(test_runs),
        "ran_graded_files": {f: (f in ran or pathlib.PurePath(f).name in ran) for f in graded_files},
        "last_test_run": test_runs[-1] if test_runs else None,
        "created_migration": any("/migrations/" in p for p in edited) or groups["migrations"] > 0,
    }

    reward = {}
    details = {}
    if (trial / "verifier" / "reward.json").exists():
        reward = json.loads((trial / "verifier" / "reward.json").read_text())
    if (trial / "verifier" / "details.json").exists():
        details = json.loads((trial / "verifier" / "details.json").read_text())
    vs_reality = {}
    mapping = ROOT / "harness" / "tickets" / f"{slug}.map.json"
    if not details:
        vs_reality = {"(no verifier result: the run did not reach grading)": {"tests": 0, "failed": 0}}
    elif mapping.exists() and (task_dir / "tests" / "must_turn_green.json").exists():
        reqs = json.loads(mapping.read_text())["requirements"]
        must_turn = json.loads((task_dir / "tests" / "must_turn_green.json").read_text())
        failed = set(details.get("failed_must_turn_green", []))
        for req in reqs:
            vs_reality[req] = {"tests": 0, "failed": 0}
        for tid in must_turn:
            name = tid.split("::")[-1]
            req = next((r for r, pats in reqs.items() if any(p in name or p in tid for p in pats)), "unmapped")
            vs_reality.setdefault(req, {"tests": 0, "failed": 0})
            vs_reality[req]["tests"] += 1
            vs_reality[req]["failed"] += tid in failed
        vs_reality = {k: v for k, v in vs_reality.items() if v["tests"]}
    messages = [s["text"] for s in steps if s["kind"] == "message"]

    timeline = []
    for s in steps:
        if s["kind"] == "message":
            timeline.append("say: " + s["text"].replace("\n", " ")[:160])
        elif s["kind"] == "command":
            timeline.append(f"run: {s['cmd'][:140]}  (exit {s['exit']})")
        else:
            timeline.append("edit: " + ", ".join(p.replace("/app/src/", "") for p in s["paths"])[:160])

    result = {
        "trial": str(trial.relative_to(ROOT)),
        "reward": reward,
        "counts": {"steps": len(steps), "commands": len(cmds), "edits": sum(s["kind"] == "edit" for s in steps),
                   "messages": len(messages), **groups},
        "files_by_layer": dict(by_layer),
        "verification": verification,
        "vs_reality": vs_reality,
        "failed_must_stay_green": len(details.get("failed_must_stay_green", [])),
        "tampered_files": details.get("tampered_files", []),
        "final_claim": messages[-1] if messages else "",
        "timeline": timeline,
    }
    (trial / "analysis.json").write_text(json.dumps(result, indent=2))
    (trial / "analysis.md").write_text(render_md(result))
    return result


def render_md(r):
    lines = [f"# Trial analysis: {r['trial']}", "", f"**Reward:** `{json.dumps(r['reward'])}`", "",
             "## Activity", "", "| | count |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in r["counts"].items()]
    lines += ["", "## Files changed by layer", ""]
    lines += [f"- **{k}**: {', '.join(v)}" for k, v in r["files_by_layer"].items()]
    v = r["verification"]
    lines += ["", "## Verification discipline", "", f"- test runs: {v['test_runs']}",
              f"- created a migration: {v['created_migration']}"]
    lines += [f"- ran graded file `{f}`: {ran}" for f, ran in v["ran_graded_files"].items()]
    if v["last_test_run"]:
        lines.append(f"- last test run: `{v['last_test_run']['cmd']}` -> {v['last_test_run']['result']}")
    lines += ["", "## Ticket requirements vs verifier", "", "| requirement | graded tests | failed |", "|---|---|---|"]
    lines += [f"| {k} | {x['tests']} | {x['failed']} |" for k, x in r["vs_reality"].items()]
    lines += ["", f"Existing tests broken: {r['failed_must_stay_green']}",
              f"Tampered files: {r['tampered_files'] or 'none'}", "", "## Final claim", "", "> " + r["final_claim"].replace("\n", "\n> "),
              "", "## Timeline", ""]
    lines += [f"{i + 1}. {t}" for i, t in enumerate(r["timeline"])]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    res = analyze(sys.argv[1])
    print(json.dumps({k: res[k] for k in ("reward", "counts", "files_by_layer", "verification", "vs_reality")}, indent=2))
