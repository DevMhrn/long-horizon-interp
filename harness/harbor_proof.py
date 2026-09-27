#!/usr/bin/env python3
"""Harbor proof: the packaged task scores 1.0 with the oracle and 0.0 with an empty agent,
the same way every time.

Runs `harbor run -a oracle` and `harbor run -a nop` --repeat times each (sequentially: the two
agents share one image name, so they must not build in parallel) and reads every trial's reward.

Pass rule:
    every oracle trial   overall == 1.0
    every nop trial      overall == 0.0
    no trial errored     (a build or verifier crash is an environment problem, not a result)

Writes output/harbor/<slug>/proof.json. Job folders live next to it.

Usage:
    python3 harness/harbor_proof.py tasks/<slug> [--repeat 3]
"""
import argparse
import json
import os
import pathlib
import shlex
import subprocess
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
# Pinned Harbor release, run through uvx so the machine's own install is untouched.
HARBOR = shlex.split(os.environ.get("HARBOR", "uvx --from harbor==0.23.0 harbor"))


def trial_rewards(job_dir):
    """[(trial, overall reward or None, exception or None)] for one Harbor job folder."""
    out = []
    for trial in sorted(p for p in job_dir.iterdir() if p.is_dir()):
        reward, err = None, None
        rj = trial / "verifier" / "reward.json"
        rt = trial / "verifier" / "reward.txt"
        if rj.exists():
            reward = json.loads(rj.read_text()).get("overall")
        elif rt.exists():
            reward = float(rt.read_text().strip() or 0)
        res = trial / "result.json"
        if res.exists():
            info = json.loads(res.read_text())
            if info.get("exception_info"):
                err = (info["exception_info"].get("exception_type") or "error")
        out.append((trial.name, reward, err))
    return out


def run_agent(task, agent, jobs_dir, label):
    job = f"{label}-{int(time.time())}"
    cmd = [*HARBOR, "run", "-p", str(task), "-a", agent, "--job-name", job, "-o", str(jobs_dir), "-q"]
    print("+", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    job_dir = jobs_dir / job
    rewards = trial_rewards(job_dir) if job_dir.exists() else []
    if not rewards:
        rewards = [(job, None, f"harbor exited {proc.returncode}: {proc.stderr[-500:]}")]
    return job, rewards


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    ap.add_argument("--repeat", type=int, default=3)
    args = ap.parse_args()
    task = pathlib.Path(args.task).resolve()
    slug = task.name
    jobs_dir = ROOT / "output" / "harbor" / slug
    jobs_dir.mkdir(parents=True, exist_ok=True)

    runs = {"oracle": [], "nop": []}
    for i in range(args.repeat):
        for agent in ("oracle", "nop"):
            job, rewards = run_agent(task, agent, jobs_dir, f"{agent}{i}")
            runs[agent].append({"job": job, "trials": [{"trial": t, "overall": r, "error": e} for t, r, e in rewards]})
            print(f"  {agent} run {i}: {[(r, e) for _, r, e in rewards]}", flush=True)

    def all_trials(agent):
        return [t for run in runs[agent] for t in run["trials"]]

    checks = {
        "oracle_all_1": all(t["overall"] == 1.0 for t in all_trials("oracle")),
        "nop_all_0": all(t["overall"] == 0.0 for t in all_trials("nop")),
        "no_errors": not any(t["error"] for a in runs for t in all_trials(a)),
    }
    proof = {"task": slug, "repeat": args.repeat, "ok": all(checks.values()), "checks": checks, "runs": runs}
    (jobs_dir / "proof.json").write_text(json.dumps(proof, indent=2))
    print(json.dumps({"ok": proof["ok"], "checks": checks}, indent=2))
    raise SystemExit(0 if proof["ok"] else 1)


if __name__ == "__main__":
    main()
