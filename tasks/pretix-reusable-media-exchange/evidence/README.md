# Evidence: pretix reusable-media exchange (single PR #6115)

This was the first probe. It showed that a single-PR feature reconstruction is **too easy** for a frontier model.

| Run folder | Model | Harness | Reward | New tests | Agent time | Verdict |
|---|---|---|---|---|---|---|
| `codex-gpt-5.5-1790526638` | openai/gpt-5.5, reasoning effort high | Codex, direct | 0.0 | 86 / 87 | 5.5 min | **Effectively solved.** The one miss (`test_exchange_mismatch_media_type`) was unfair: the instruction did not say which check wins when two apply. The instruction now lists the check order. |

This result moved the work toward harder, multi-PR tasks.
