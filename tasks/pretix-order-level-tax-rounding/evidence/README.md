# Evidence: pretix order-level tax rounding (single PR #5019)

This is the single-PR probe that led to the multi-PR chain in `tasks/pretix-tax-compliance-chain/`.

| Run folder | Model | Harness | Reward | New tests | Existing broken | Agent time | Verdict |
|---|---|---|---|---|---|---|---|
| `codex-gpt-5.6-sol-1790536476` | openai/gpt-5.6-sol | Codex, direct | **0.0** | 28 / 33 | 0 | 20.5 min | **Fail**, with 3 fair misses: order split balance, web checkout placement, cart net total. 2 misses were borderline: the ticket did not yet say that no payment fee applies before a payment method is chosen. That sentence was added later. |

`gates/` holds the package report, red-team, network check and Harbor oracle/nop proof for this task. Each run folder has the reward, the failed tests, the trace analysis, the trajectory and the raw agent log.
