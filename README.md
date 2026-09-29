# long-horizon-interp

Long-horizon, hard-but-fair agent tasks built from real feature work on [pretix](https://github.com/pretix/pretix), in Harbor format.

## 📦 Submission: one task

> **The submission is [`submission/pretix-tax-compliance-chain.zip`](submission/pretix-tax-compliance-chain.zip).**
> It contains exactly one Harbor task directory: `pretix-tax-compliance-chain/`.

| | |
|---|---|
| Task | `collinear-candidate/pretix-tax-compliance-chain` |
| Zip | [`submission/pretix-tax-compliance-chain.zip`](submission/pretix-tax-compliance-chain.zip) |
| Checksum (SHA-256) | [`submission/pretix-tax-compliance-chain.zip.sha256`](submission/pretix-tax-compliance-chain.zip.sha256): `6630406b5ebad99685433e8e917246e514f6c658cd310d4e39ed9969315e06f3` |
| Frozen task image (proof of what was tested) | [`ghcr.io/devmhrn/pretix-tax-compliance-chain:v1`](https://github.com/users/DevMhrn/packages/container/package/pretix-tax-compliance-chain), multi-arch digest `sha256:611d41d51c79cc1eb17c2f10698ae3f2b5e4460e58b32574c7161f159475d3de`. It contains amd64 `sha256:39f48b58…` and arm64 `sha256:09fb25a2…`, the exact images verified in [`evidence/gates/clean_build_*.json`](tasks/pretix-tax-compliance-chain/evidence/gates/). |
| Browsable copy | [`tasks/pretix-tax-compliance-chain/`](tasks/pretix-tax-compliance-chain/), identical to the zip contents |

**What it is.** A multi-PR feature-reconstruction task: three related features around taxes, fees and cancellations are removed from pretix, and the agent rebuilds them from one product ticket.
- **GPT-5.5-high (Codex) and Claude Opus 4.7 (Claude Code) both score 0.0**, and so does GPT-5.6-sol. Every counted failure maps to a requirement stated in the instruction.
- The oracle scores 1.0 and an empty agent scores 0.0, each repeated 3 times under Harbor.
- The clean build is verified on **linux/amd64 and linux/arm64**.

**Read next:**
- [task README](tasks/pretix-tax-compliance-chain/README.md): a one-page overview
- [RUN_REPORT](tasks/pretix-tax-compliance-chain/RUN_REPORT.md): the approach, pre-QA checks, model runs, failure analysis and fairness audit
- [evidence](tasks/pretix-tax-compliance-chain/evidence/README.md): gate reports and every model run

**Run it:**

```bash
cd submission && shasum -a 256 -c pretix-tax-compliance-chain.zip.sha256 && cd ..   # verify the download
unzip submission/pretix-tax-compliance-chain.zip
harbor run -p ./pretix-tax-compliance-chain -a oracle                                  # expect 1.0 (Harbor >= 0.23)
harbor run -p ./pretix-tax-compliance-chain -a codex -m openai/gpt-5.5 --ak reasoning_effort=high
harbor run -p ./pretix-tax-compliance-chain -a claude-code -m anthropic/claude-opus-4.7
harbor view ./jobs
```

The frozen image is published only as evidence of exactly what was built and tested. It is the **task image**, the environment the agent starts in:
- pretix at the pinned commit, with the three features removed;
- the pinned Codex and Claude Code CLIs;
- no tests, no solution and no `.git` history.

The task itself builds this environment from `environment/Dockerfile`:

```bash
docker pull ghcr.io/devmhrn/pretix-tax-compliance-chain@sha256:611d41d51c79cc1eb17c2f10698ae3f2b5e4460e58b32574c7161f159475d3de
```

## Supporting material (not part of the submission)

These show how the task was produced. None of it is needed to run the task.

| Path | What it is |
|---|---|
| `harness/` | The tooling that found, built, checked and ran the tasks: PR mining, environment building, behaviour proof, chain checks, package checks, Harbor proof, attack and network checks, clean-build check, trace analysis. See [harness/README.md](harness/README.md) and [harness/GATES.md](harness/GATES.md). |
| `tasks/pretix-order-level-tax-rounding/`, `tasks/pretix-reusable-media-exchange/` | The single-PR probes that led to the chain (RUN_REPORT §4) |
| `tasks/*` (others) | Other screened single-PR tasks that pass the oracle/nop proof. Not probed with models. |
| `output/` | Local clones, images and raw runs (git-ignored) |

API keys live in a local, git-ignored `.env` (template: `.env.example`).
