#!/usr/bin/env python3
"""Hardness sits: run a real agent + model on a task and summarize what happened.

Keys come from <repo>/.env and reach Harbor only through the process environment (never --ae),
so they are not written into job configs. After the run, every job file is scanned for the key
values and any hit is redacted and reported.

For each trial it records the reward breakdown plus the horizon of the attempt: agent steps,
tool calls, wall time and tokens, read from the trial's result.json and trajectory.

Usage:
    python3 harness/run_model.py tasks/<slug> [--agent claude-code] [--model anthropic/...] [-k 1]
Outputs:
    output/runs/<slug>/<job>/...        Harbor job folders
    output/runs/<slug>/sits.json        one row per trial
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import shlex
import subprocess
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARBOR = shlex.split(os.environ.get("HARBOR", "uvx --from harbor==0.23.0 harbor"))
SECRET_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "OPENROUTER_API_KEY")
OPENROUTER_BASE = "https://openrouter.ai/api"


def load_env(path=ROOT / ".env"):
    env = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def scrub(job_dir, secrets):
    """Redact any key value that ended up in a job file. Returns the files that contained one."""
    hits = []
    for f in job_dir.rglob("*"):
        if not f.is_file() or f.stat().st_size > 50_000_000:
            continue
        try:
            text = f.read_text(errors="ignore")
        except OSError:
            continue
        if any(s in text for s in secrets):
            for s in secrets:
                text = text.replace(s, "[REDACTED]")
            f.write_text(text)
            hits.append(str(f.relative_to(job_dir)))
    return hits


def seconds(a, b):
    try:
        return round((dt.datetime.fromisoformat(b) - dt.datetime.fromisoformat(a)).total_seconds())
    except Exception:
        return None


def summarize_trial(trial):
    row = {"trial": trial.name}
    rj = trial / "verifier" / "reward.json"
    if rj.exists():
        row["reward"] = json.loads(rj.read_text())
    res = trial / "result.json"
    if res.exists():
        info = json.loads(res.read_text())
        exc = info.get("exception_info") or {}
        row["exception"] = exc.get("exception_type")
        agent = info.get("agent_result") or {}
        row["tokens"] = {k: agent.get(k) for k in ("n_input_tokens", "n_cache_tokens", "n_output_tokens")}
        ae = info.get("agent_execution") or {}
        row["agent_seconds"] = seconds(ae.get("started_at"), ae.get("finished_at"))
    traj = trial / "agent" / "trajectory.json"
    if traj.exists():
        steps = json.loads(traj.read_text()).get("steps", [])
        row["steps"] = len(steps)
        row["tool_calls"] = sum(len(s.get("tool_calls") or []) for s in steps)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    ap.add_argument("--agent")
    ap.add_argument("--model")
    ap.add_argument("-k", type=int, default=1, help="number of attempts")
    ap.add_argument("--via", choices=["direct", "openrouter"], help="route the model API (default: claude-code via "
                                                                     "OpenRouter if its key is set, codex direct)")
    args = ap.parse_args()

    env_file = load_env()
    agent = args.agent or env_file.get("AGENT", "claude-code")
    model = args.model or env_file.get("MODEL")
    # claude-code goes through OpenRouter whenever its key is set; codex only when asked (--via openrouter).
    via_openrouter = bool(env_file.get("OPENROUTER_API_KEY")) and (
        args.via == "openrouter" or (args.via is None and agent == "claude-code"))
    if via_openrouter:
        needed = "OPENROUTER_API_KEY"
    else:
        needed = "OPENAI_API_KEY" if agent == "codex" else "ANTHROPIC_API_KEY"
    if not env_file.get(needed):
        raise SystemExit(f"{needed} is empty in {ROOT / '.env'}")
    if via_openrouter and agent == "codex":
        # Codex speaks the OpenAI Responses API, which OpenRouter serves at /api/v1.
        env_file = {**env_file, "OPENAI_BASE_URL": OPENROUTER_BASE + "/v1",
                    "OPENAI_API_KEY": env_file["OPENROUTER_API_KEY"]}
    elif via_openrouter:
        # Claude Code speaks the Anthropic API; OpenRouter serves an Anthropic-compatible endpoint that
        # accepts the key as x-api-key. Harbor resolves the first *present* credential variable (even an
        # empty one) and passes it on as ANTHROPIC_API_KEY, so the key must go there directly.
        env_file = {**env_file, "ANTHROPIC_BASE_URL": OPENROUTER_BASE,
                    "ANTHROPIC_API_KEY": env_file["OPENROUTER_API_KEY"]}

    task = pathlib.Path(args.task).resolve()
    jobs = ROOT / "output" / "runs" / task.name
    jobs.mkdir(parents=True, exist_ok=True)
    job = f"{agent}-{(model or 'default').split('/')[-1]}-{int(time.time())}"
    cmd = [*HARBOR, "run", "-p", str(task), "-a", agent, "-k", str(args.k), "--job-name", job, "-o", str(jobs)]
    if model:
        cmd += ["-m", model]
    effort = env_file.get("REASONING_EFFORT")
    if agent == "codex" and effort:
        cmd += ["--ak", f"reasoning_effort={effort}"]
    print("+", " ".join(cmd), flush=True)
    child_env = {**os.environ, **{k: v for k, v in env_file.items() if v}}
    if via_openrouter:
        child_env.pop("ANTHROPIC_AUTH_TOKEN", None)
    subprocess.run(cmd, env=child_env)

    job_dir = jobs / job
    secrets = [env_file[k] for k in SECRET_KEYS if env_file.get(k)]
    leaked = scrub(job_dir, secrets) if job_dir.exists() else []
    trials = [summarize_trial(t) for t in sorted(job_dir.iterdir()) if t.is_dir()] if job_dir.exists() else []
    record = {"task": task.name, "agent": agent, "model": model, "via": "openrouter" if via_openrouter else "direct", "reasoning_effort": effort, "job": job, "k": args.k,
              "key_leaks_redacted": leaked, "trials": trials}
    sits = jobs / "sits.json"
    history = json.loads(sits.read_text()) if sits.exists() else []
    sits.write_text(json.dumps(history + [record], indent=2))
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
