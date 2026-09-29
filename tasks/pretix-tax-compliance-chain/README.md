# collinear-candidate/pretix-tax-compliance-chain

A multi-PR feature-reconstruction task on [pretix](https://github.com/pretix/pretix), an open-source ticketing system for events and festivals.

The agent works in pretix as it would look if three real, related features around taxes, fees and cancellations had never been built. From one product ticket it has to build all three:

- **A. Default tax rule and fee taxation:** one default tax rule per event, payment-fee and cancellation-fee tax modes, and splitting a fee proportionally across the order's tax rates.
- **B. Safe event cancellation:** a side-effect-free dry run that reports exactly how much money a bulk cancellation would owe back to customers.
- **C. Order-level tax rounding:** three rounding modes with one-cent line corrections (the calculation e-invoicing standards such as EN 16931 require), applied consistently in the cart, checkout, web and API order placement, payment changes and every order change.

It is graded by the original developers' tests:
- **517 tests must turn green.** 72 of them were written for these three features. The other 445 are existing checkout, order and API tests whose shared test setup uses the new default-tax-rule field, so they only pass once that part is built correctly.
- **1,430 existing tests must stay green.**

| | |
|---|---|
| Category | software engineering / long-horizon feature work |
| Stack | Python 3.11, Django, SQLite, pytest (pretix at commit `3e972edd`, Oct 2025) |
| Gold change | 42 product files, +1,763 / −405 lines, including a database migration |
| Expert estimate | ~20 hours |
| Agent limits | 2 h, 4 CPUs, 8 GB RAM, runs as non-root `agent`, network limited to model APIs |
| Verifier | 15 min, no network, own copy of the tests, anti-tamper checks |

## Results

| Model | Harness | API route | Instruction | Reward | New tests passed | Existing broken | Time |
|---|---|---|---|---|---|---|---|
| **GPT-5.5** (reasoning effort high) | Codex 0.158.0 | OpenRouter | final | **0.0** | 494 / 517 | 0 | 17 min |
| **Claude Opus 4.7** | Claude Code 2.1.284 | OpenRouter | final | **0.0** | 503 / 517 | 0 | 25 min |
| GPT-5.6-sol (reasoning effort high) | Codex 0.158.0 | OpenAI API | earlier draft¹ | **0.0** | 507 / 517 | 4 | 19 min |

The first two rows are the brief's target models, run on the final instruction. ¹ GPT-5.6-sol is extra evidence, run before two instruction fixes. The failures caused by that older wording are marked "not counted" in the RUN_REPORT, and its remaining failures are all fair.

The oracle scores 1.0 and an empty agent scores 0.0. Every counted failure maps to a requirement stated in `instruction.md`. See **[RUN_REPORT.md](RUN_REPORT.md)** for the full story, checks, fairness audit and failure analysis, and **[evidence/](evidence/README.md)** for the raw runs.

## Long-horizon profile

| Task scope | |
|---|---|
| Linked subgoals | 3 (A, B, C above), feeding into each other |
| Gold change | 42 files, +1,763 / −405 lines, across admin UI, services, API, migrations, models, shop checkout and settings |
| Graded tests | 517 must turn green, 1,430 must stay green, in 14 test files |
| Expert estimate | about 20 hours |

| Per run | GPT-5.5-high | Claude Opus 4.7 | GPT-5.6-sol |
|---|---|---|---|
| Agent time | 17.1 min | 24.7 min | 18.9 min |
| Steps / tool calls | 155 / 200 | 182 / 177 | 184 / 178 |
| Product files changed (layers) | 17 (6) | 13 (6) | 18 (7) |
| Test runs by the agent | 29 | 30 | 20 |
| Graded test files it ran | 8 of 14 | 10 of 14 | 9 of 14 |
| Hit the 2-hour limit | no | no | no |

Details and sources: RUN_REPORT §9 and `evidence/long_horizon_profile.json`.

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

**Network during the build.** Building the image needs internet access. It downloads:
- the pinned pretix commit from GitHub;
- Node.js from nodejs.org (checksum-verified);
- the pinned Python packages from PyPI;
- the pinned Codex and Claude Code CLIs from npm.

While the agent works, only the model APIs are reachable. The verifier has no network at all.
