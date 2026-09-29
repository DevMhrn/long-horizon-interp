# Evidence: pretix tax-compliance chain

This folder holds everything needed to check that this task is **solvable, hardened, and failed fairly by frontier models**. The files are copies of Harbor job output, produced by `harness/collect_evidence.py`.
- API keys were never passed to Harbor, and every file here was scanned for them.
- Harbor's `agent/sessions/` folders are not included; they duplicate `agent_log.txt.gz`.
- The agent never sees this folder: only `environment/` is built into the task image.

## Gates (task quality, before any model run)

| File | What it shows |
|---|---|
| `gates/behavior_screen.json` | Without the feature, 517 tests fail. With the gold patch they pass, and 1,430 existing tests stay green. Stable over 3 + 3 runs: 0 flaky, 0 broken by gold. |
| `gates/chain_members.json` | Each PR in the chain owns graded tests: #4962 owns 17, #5565 owns 23, #5019 owns 32. No member owns 90% or more. The other 445 tests need the new `TaxRule.default` field. |
| `gates/package_report.json` | Static checks: files, `task.toml`, Dockerfile policy, secrets, size, no leak of PR/commit/file names in the instruction, no implementation-only names, and every new name a test relies on is stated. |
| `gates/redteam.json` | 7 cheating attempts run as the unprivileged agent user. All either landed and scored 0, or were refused by the OS. Afterwards oracle = 1.0 and nop = 0.0. |
| `gates/network_check.json` | During the agent phase only `api.openai.com`, `api.anthropic.com` and `openrouter.ai` are reachable. GitHub, PyPI and everything else is blocked. |
| `gates/harbor_oracle_nop_proof.json` | `harbor run -a oracle` → 1.0 and `harbor run -a nop` → 0.0, each repeated 3 times, no errors. |
| `gates/clean_build_arm64.json`, `gates/clean_build_amd64.json` | Clean-machine proof on both platforms: `environment/` built with `--no-cache --pull`, then nop → 0.0 and oracle → 1.0 with plain Docker. amd64 is a real `x86_64` image with 0 cached layers, built on Apple Silicon via emulation. Script: `harness/verify_clean_build.sh`. |

## Model runs

All three models that actually worked on the task scored **overall 0.0**.

| Run folder | Model (reported by the trajectory) | Harness | Instruction | Reward | New tests | Existing broken | Agent time | Verdict |
|---|---|---|---|---|---|---|---|---|
| `codex-gpt-5.5-1790626951` | **openai/gpt-5.5**, reasoning effort high | Codex 0.158.0, via OpenRouter | final | **0.0** | 494 / 517 | 0 | 17.1 min | **Fair fail**: 23 misses, all in stated requirements |
| `claude-code-claude-opus-4.7-1790625274` | **anthropic/claude-opus-4.7** | Claude Code 2.1.284, via OpenRouter | final | **0.0** | 503 / 517 | 0 | 24.7 min | **Fair fail**: 14 misses, all in stated requirements |
| `codex-gpt-5.6-sol-1790585007` | openai/gpt-5.6-sol, reasoning effort high | Codex 0.158.0, direct | earlier draft | **0.0** | 507 / 517 | 4 | 18.9 min | **Fail**, with 8 fair misses. 5 misses traced to draft wording that was then corrected. |
| `claude-code-claude-opus-4.7-1790625138` | – | Claude Code | final | – | – | – | 3 s | **Infra, not counted**: authentication misconfigured in the runner, so the agent never worked |
| `codex-gpt-5.6-sol-1790583538` | – | Codex | draft | – | – | – | – | **Infra, not counted**: Debian mirror returned 403 during agent setup |
| `codex-gpt-5.6-sol-1790584578` | – | Codex | draft | – | – | – | – | **Infra, not counted**: TLS error downloading nvm during agent setup |

The infra failures led to fixes in the task image:
- Node.js now comes from the checksum-pinned official release.
- The Codex and Claude Code CLIs are pinned in the image, so agent setup needs no network.
- The runner passes OpenRouter credentials correctly.

In each run folder:
- `summary.json`: model, versions, reward, steps, tool calls, time, tokens.
- `details.json`: which graded tests failed.
- `analysis.md`: the trace analysis. It covers files changed per layer, which graded test files the agent ran, failures mapped to ticket requirements, and the agent's final claim.
- `trajectory.json.gz`: the ATIF trajectory.
- `agent_log.txt.gz`: the raw agent event stream.
- `pytest.log.gz`: the verifier output.

## Why the failures are fair

**The task is solvable:**
- the oracle scores 1.0;
- the environment is stable (0 flaky tests);
- the verifier runs with no network.

**Every failing test maps to a requirement stated in `instruction.md`.** The per-run `analysis.md` shows the mapping. The instruction states exact names, values, precedence rules and worked examples. It never names files or implementation.

**All three models failed in the same places:**
1. **Consistency across paths.** The rounding algorithm itself is mostly right. Applying it everywhere the ticket lists is not: web checkout, API order creation and simulation, order changes and splits. `test_rounding_sum_by_net` (web checkout) and `test_split_with_rounding_change` failed for every model.
2. **Checking only part of the work.** Each model skipped graded test files that were present in `/app` and would have caught its bugs. GPT-5.5 skipped the checkout and rounding unit tests, Opus 4.7 skipped the checkout tests, and GPT-5.6-sol skipped the admin event tests.
3. **Claiming more than was checked.** Every model's final message reports the wiring as complete.

## Reproduce

```bash
harbor run -p tasks/pretix-tax-compliance-chain -a oracle
harbor run -p tasks/pretix-tax-compliance-chain -a codex -m openai/gpt-5.5 --ak reasoning_effort=high
harbor run -p tasks/pretix-tax-compliance-chain -a claude-code -m anthropic/claude-opus-4.7
harbor view ./jobs
```

The runs above used `harness/run_model.py` (Harbor 0.23.0 via `uvx`), which routes through OpenRouter when `OPENROUTER_API_KEY` is set.
