# long-horizon-interp

Long-horizon, hard-but-fair agent tasks built from real feature work on [pretix](https://github.com/pretix/pretix), in Harbor format.

## Submission

**[`tasks/pretix-tax-compliance-chain/`](tasks/pretix-tax-compliance-chain/)** is a multi-PR feature-reconstruction task: three related tax features removed together, to be rebuilt from one ticket.
- GPT-5.5-high, Claude Opus 4.7 and GPT-5.6-sol all score 0.0, and each counted failure maps to a stated requirement.
- The oracle scores 1.0.
- See its [README](tasks/pretix-tax-compliance-chain/README.md), [RUN_REPORT](tasks/pretix-tax-compliance-chain/RUN_REPORT.md) and [evidence](tasks/pretix-tax-compliance-chain/evidence/README.md).

## Repository layout

| Path | What it is |
|---|---|
| `tasks/pretix-tax-compliance-chain/` | the submitted task |
| `tasks/pretix-order-level-tax-rounding/`, `tasks/pretix-reusable-media-exchange/` | single-PR probes that led to the chain, with their evidence |
| `tasks/*` (others) | further screened single-PR tasks that pass the oracle/nop proof; not probed |
| `harness/` | the tooling that found, built, checked and ran the tasks (see [harness/README.md](harness/README.md) and [harness/GATES.md](harness/GATES.md)) |
| `output/` | local clones, images and raw runs (git-ignored) |

API keys live in a local, git-ignored `.env` (template: `.env.example`).
