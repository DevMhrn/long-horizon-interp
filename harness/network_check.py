#!/usr/bin/env python3
"""Network check: prove the agent phase can reach its model API and nothing else.

Copies the task, swaps its solution for task_template/network_probe.sh and runs it through
Harbor's oracle agent, which runs under the same [agent] network policy and user as a real agent.
Passes only if every non-model URL is blocked, both model APIs are reachable, and the probe ran
as the unprivileged agent user.

Usage:
    python3 harness/network_check.py tasks/<slug>
"""
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARBOR = shlex.split(os.environ.get("HARBOR", "uvx --from harbor==0.23.0 harbor"))
MODEL_APIS = ("api.anthropic.com", "api.openai.com")


def main():
    task = pathlib.Path(sys.argv[1]).resolve()
    work = ROOT / "output" / "netprobe"
    probe = work / f"{task.name}-netprobe"
    shutil.rmtree(probe, ignore_errors=True)
    shutil.copytree(task, probe)
    toml = (probe / "task.toml").read_text()
    (probe / "task.toml").write_text(re.sub(r'^name = ".*"$', f'name = "collinear-candidate/{probe.name}"', toml, flags=re.M))
    shutil.copy(ROOT / "harness" / "task_template" / "network_probe.sh", probe / "solution" / "solve.sh")
    job = f"netprobe-{task.name}-{int(time.time())}"
    subprocess.run([*HARBOR, "run", "-p", str(probe), "-a", "oracle", "--job-name", job, "-o", str(work / "jobs"), "-q"],
                   capture_output=True)
    trials = [t for t in (work / "jobs" / job).iterdir() if t.is_dir()]
    text = (trials[0] / "agent" / "netprobe.txt").read_text() if trials else ""
    lines = [l for l in text.splitlines() if l.startswith("https://") or l.startswith("git ")]
    blocked_ok = all("BLOCKED" in l for l in lines if not any(api in l for api in MODEL_APIS))
    apis_ok = all(any(api in l and "REACHABLE" in l for l in lines) for api in MODEL_APIS)
    user_ok = "user = agent" in text
    report = {"task": task.name, "ok": bool(lines) and blocked_ok and apis_ok and user_ok,
              "checks": {"non_model_hosts_blocked": blocked_ok, "model_apis_reachable": apis_ok, "runs_as_agent": user_ok},
              "probe": text.splitlines()}
    (work / f"{task.name}.json").write_text(json.dumps(report, indent=2))
    print(text)
    print("NETWORK CHECK:", "PASS" if report["ok"] else "FAIL", report["checks"])
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
