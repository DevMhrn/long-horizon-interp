# collinear-candidate/pretix-tax-compliance-chain

A multi-PR feature-reconstruction task on [pretix](https://github.com/pretix/pretix), an open-source ticketing system for events and festivals.

The agent works in pretix as it would look if three real, related tax features had never been built. From one product ticket it has to build all three:

- **A. Default tax rule and fee taxation:** one default tax rule per event, payment-fee and cancellation-fee tax modes, and splitting a fee proportionally across the order's tax rates.
- **B. Safe event cancellation:** a side-effect-free dry run that reports exactly how much money a bulk cancellation would owe back to customers.
- **C. Order-level tax rounding:** three rounding modes with one-cent line corrections (the calculation e-invoicing standards such as EN 16931 require), applied consistently in the cart, checkout, web and API order placement, payment changes and every order change.

It is graded by the original developers' tests: **517 tests must turn green** and **1,430 existing tests must stay green**.

| | |
|---|---|
| Category | software engineering / long-horizon feature work |
| Stack | Python 3.11, Django, SQLite, pytest (pretix at commit `3e972edd`, Oct 2025) |
| Gold change | 42 product files, +1,763 / −405 lines, including a database migration |
| Expert estimate | ~20 hours |
| Agent limits | 2 h, 4 CPUs, 8 GB RAM, runs as non-root `agent`, network limited to model APIs |
| Verifier | 15 min, no network, own copy of the tests, anti-tamper checks |

## Results

| Model | Harness | Reward | New tests passed | Existing broken | Time |
|---|---|---|---|---|---|
| GPT-5.5 (reasoning effort high) | Codex 0.158.0 | **0.0** | 494 / 517 | 0 | 17 min |
| Claude Opus 4.7 | Claude Code 2.1.284 | **0.0** | 503 / 517 | 0 | 25 min |
| GPT-5.6-sol (reasoning effort high) | Codex 0.158.0 | **0.0** | 507 / 517 | 4 | 19 min |

The oracle scores 1.0 and an empty agent scores 0.0. Every counted failure maps to a requirement stated in `instruction.md`. See **[RUN_REPORT.md](RUN_REPORT.md)** for the full story, checks, fairness audit and failure analysis, and **[evidence/](evidence/README.md)** for the raw runs.

## Layout

```
instruction.md          the ticket the agent receives
task.toml               metadata, timeouts, resources, network policy
environment/            Dockerfile, pinned lock, and the patch that removes the three features at build time
solution/solve.sh       oracle: applies the original PRs' product code (solution/gold.patch)
tests/test.sh           verifier: restores its own tests, removes stray pytest hooks, runs pytest, writes reward.json
tests/grade.py          reward: overall, must_turn_green, must_stay_green, integrity
evidence/               gate reports and every model run (trajectories, logs, analyses)
RUN_REPORT.md           how the task was found, built, checked and run
```

## Run it

```bash
harbor run -p ./pretix-tax-compliance-chain -a oracle
harbor run -p ./pretix-tax-compliance-chain -a codex -m openai/gpt-5.5 --ak reasoning_effort=high
harbor run -p ./pretix-tax-compliance-chain -a claude-code -m anthropic/claude-opus-4.7
harbor view ./jobs
```

This requires Harbor ≥ 0.23, for the non-root agent user and the per-phase network allowlist.
