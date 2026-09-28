#!/usr/bin/env python3
"""Copy the evidence for a task into tasks/<slug>/evidence/, scrubbed and compact.

    evidence/
        gates/            package report, red-team, network probe, Harbor oracle/nop proof, screen + members
        runs/<job>/       one folder per model run:
            summary.json      model, harness, route, reward, horizon (steps, tool calls, time, tokens)
            reward.json       verifier reward
            details.json      failed must_turn_green / must_stay_green test ids
            analysis.md       trace analysis (requirements vs verifier, verification discipline, claim)
            trajectory.json.gz    ATIF trajectory written by Harbor
            agent_log.txt.gz      raw agent event stream (codex.txt / claude-code.txt)
            pytest.log.gz         verifier pytest output
            exception.txt         only for runs that errored (infra failures)

Harbor's agent/sessions folders are not copied: they duplicate the raw log and may carry client config.
Every copied file is scanned for the key values in .env and common key patterns; a hit aborts.

Usage:
    python3 harness/collect_evidence.py <slug> [--screen chainA]
"""
import argparse
import gzip
import json
import pathlib
import re
import shutil

ROOT = pathlib.Path(__file__).resolve().parent.parent
KEY_RE = re.compile(r"sk-or-v1-[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|sk-proj-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{40,}|"
                    r"ghp_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----")


def secrets():
    env = ROOT / ".env"
    vals = []
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                if ("KEY" in k or "TOKEN" in k) and len(v.strip()) > 12:
                    vals.append(v.strip())
    return vals


def copy(src, dst, compress=False):
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if compress:
        with open(src, "rb") as f, gzip.open(str(dst) + ".gz", "wb", compresslevel=9) as g:
            shutil.copyfileobj(f, g)
    else:
        shutil.copy(src, dst)


def summarize(trial, job):
    res = json.loads((trial / "result.json").read_text()) if (trial / "result.json").exists() else {}
    cfg = json.loads((trial / "config.json").read_text()) if (trial / "config.json").exists() else {}
    agent_cfg = cfg.get("agent", {})
    traj = trial / "agent" / "trajectory.json"
    steps = tools = None
    agent_version = model_seen = None
    if traj.exists():
        t = json.loads(traj.read_text())
        steps = len(t.get("steps", []))
        tools = sum(len(s.get("tool_calls") or []) for s in t.get("steps", []))
        agent_version = (t.get("agent") or {}).get("version")
        model_seen = sorted({s.get("model_name") for s in t.get("steps", []) if s.get("model_name")})
    ae = res.get("agent_execution") or {}
    return {
        "job": job.name,
        "trial": trial.name,
        "agent": agent_cfg.get("name"),
        "agent_version": agent_version,
        "model_requested": agent_cfg.get("model_name"),
        "model_reported_by_trajectory": model_seen,
        "agent_kwargs": agent_cfg.get("kwargs"),
        "reward": (res.get("verifier_result") or {}).get("rewards"),
        "exception": (res.get("exception_info") or {}).get("exception_type"),
        "agent_started": ae.get("started_at"),
        "agent_finished": ae.get("finished_at"),
        "steps": steps,
        "tool_calls": tools,
        "tokens": {k: (res.get("agent_result") or {}).get(k) for k in ("n_input_tokens", "n_cache_tokens", "n_output_tokens")},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--screen", help="screen dir under output/screens (e.g. chainA, pr5019)")
    args = ap.parse_args()
    task = ROOT / "tasks" / args.slug
    ev = task / "evidence"
    shutil.rmtree(ev, ignore_errors=True)
    gates = ev / "gates"
    copy(task / ".package_report.json", gates / "package_report.json")
    copy(ROOT / "output" / "redteam" / f"{args.slug}.json", gates / "redteam.json")
    copy(ROOT / "output" / "netprobe" / f"{args.slug}.json", gates / "network_check.json")
    copy(ROOT / "output" / "harbor" / args.slug / "proof.json", gates / "harbor_oracle_nop_proof.json")
    if args.screen:
        sdir = ROOT / "output" / "screens" / args.screen
        copy(sdir / "screen.json", gates / "behavior_screen.json")
        copy(sdir / "members.json", gates / "chain_members.json")

    rows = []
    runs = ROOT / "output" / "runs" / args.slug
    for job in sorted(p for p in runs.iterdir() if p.is_dir()) if runs.exists() else []:
        for trial in sorted(p for p in job.iterdir() if p.is_dir()):
            out = ev / "runs" / job.name
            s = summarize(trial, job)
            out.mkdir(parents=True, exist_ok=True)
            (out / "summary.json").write_text(json.dumps(s, indent=2))
            copy(trial / "verifier" / "reward.json", out / "reward.json")
            copy(trial / "verifier" / "details.json", out / "details.json")
            copy(trial / "analysis.md", out / "analysis.md")
            copy(trial / "agent" / "trajectory.json", out / "trajectory.json", compress=True)
            for raw in ("codex.txt", "claude-code.txt"):
                copy(trial / "agent" / raw, out / "agent_log.txt", compress=True)
            copy(trial / "verifier" / "pytest.log", out / "pytest.log", compress=True)
            if s["exception"]:
                copy(trial / "exception.txt", out / "exception.txt")
            rows.append(s)
    (ev / "runs_index.json").write_text(json.dumps(rows, indent=2))

    vals, hits = secrets(), []
    for f in ev.rglob("*"):
        if not f.is_file():
            continue
        data = gzip.open(f).read() if f.suffix == ".gz" else f.read_bytes()
        text = data.decode("utf-8", "ignore")
        if any(v in text for v in vals) or KEY_RE.search(text):
            hits.append(str(f.relative_to(ROOT)))
    if hits:
        shutil.rmtree(ev)
        raise SystemExit(f"ABORTED, secret found in: {hits}")
    size = sum(f.stat().st_size for f in ev.rglob("*") if f.is_file()) / 1e6
    print(f"{ev.relative_to(ROOT)}: {len(rows)} runs, {size:.1f} MB, secret scan clean")


if __name__ == "__main__":
    main()
