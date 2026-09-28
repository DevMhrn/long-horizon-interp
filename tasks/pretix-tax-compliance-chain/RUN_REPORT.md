# RUN REPORT: pretix tax-compliance chain

**Task:** `collinear-candidate/pretix-tax-compliance-chain`

**Result:** GPT-5.5-high, Claude Opus 4.7 and GPT-5.6-sol all score **overall 0.0**, and every failure I count traces to a requirement the instruction states. The oracle scores 1.0 and an empty agent scores 0.0. The environment is stable, hardened and cut off from the internet.

This report covers:
1. [How I got here](#1-how-i-got-here): the story and the decisions
2. [Why I built the Docker environment first](#2-why-i-built-the-docker-environment-first)
3. [How candidates were found](#3-how-candidates-were-found): mining and the behaviour proof
4. [From single PR to multi-PR](#4-from-single-pr-to-multi-pr): what the probes taught me
5. [How the chain task is built](#5-how-the-chain-task-is-built)
6. [The instruction](#6-the-instruction): how it was written to be fair
7. [Verifier design](#7-verifier-design)
8. [Pre-QA checks](#8-pre-qa-checks): every check, and why it exists
9. [Model runs and failure analysis](#9-model-runs-and-failure-analysis)
10. [Fairness audit](#10-fairness-audit): including the mistakes I found and fixed
11. [Realism and economic value](#11-realism-and-economic-value)
12. [Provenance and licences](#12-provenance-and-licences)
13. [Limitations](#13-limitations)
14. [Reproduction](#14-reproduction)

---

## 1. How I got here

**The target.** A task that is *hard because of the work*, not because of tricks:
- the agent has to plan, explore a large codebase, keep many rules consistent, verify its own work, and ship a real change;
- a precise instruction must still leave the task hard;
- the verifier must not be foolable.

**Choosing a codebase.** I wanted a real, large, stateful domain with money in it, where "almost right" is still wrong. pretix fits well:
- about 285k lines of Django;
- orders, payments, fees, taxes, refunds, check-in;
- a deep test suite of 225 test files;
- it runs fully offline on SQLite.

**Choosing the kind of task.** I considered three kinds:

| Option | Why I did / didn't use it |
|---|---|
| Bug fixing | Strong models fix isolated bugs quickly, so there's too little long-horizon work |
| New feature from scratch | There is no trusted definition of "correct", so I'd have to invent the grading |
| **Feature reconstruction** ✅ | A feature the maintainers really built is removed, and the agent rebuilds it. The maintainers' own code is the proof it's solvable. Their tests, written before anyone knew about this task, are the grader. |

**The path, in order:**
1. Built a trustworthy Docker environment first (§2).
2. Mined pretix's history for feature PRs and proved which ones form clean tasks (§3).
3. Hardened and packaged the tasks, then probed single-PR tasks on frontier models (§4):
   - #6115 (reusable-media exchange) was essentially solved in 5.5 minutes, so it was too easy;
   - #5019 (order-level tax rounding) failed fairly, but narrowly.
4. Took the lesson from the #5019 trace: the models get the algorithm right and fail at **applying one rule consistently across many code paths**. So I combined #5019 with the two related tax PRs it builds on into one chain (§5).
5. Ran the chain on the two target models and one newer model. All three failed fairly (§9), and I audited every failure against the instruction (§10).

---

## 2. Why I built the Docker environment first

Every later judgement depends on the environment. If a test is flaky, "the model broke it" means nothing. If the image isn't the right commit, "the oracle passes" proves nothing. If dependencies drift, nobody can reproduce the result. So before looking at a single task, I built and certified the base environment.

**Rules I followed:**
- **Exact commit, no history.** The source comes from `git archive` of one commit, and the image never contains `.git`, so an agent cannot mine history for the answer.
- **Follow the project's own CI.** The Python version is read from each commit's own CI matrix (the version its SQLite job uses): 3.11 for 2025 commits, 3.13 for 2026.
- **Pins come from a working container, never from guesses.**
  - The first build resolves dependencies *as of the commit date* (`uv --exclude-newer <commit date>`).
  - The container that installed and imported successfully is frozen into a per-commit lock.
  - The image is rebuilt from that lock.
- **The base image is pinned by digest.**
- **Determinism:** `TZ=UTC`, `LANG`/`LC_ALL=C.UTF-8` and `PYTHONHASHSEED=0` are set, and the test order is not randomised.
- **Never change product code or weaken tests to get a green run.** Every failure is classified first: environment problem, stale test, product defect, or harness bug.

**The box check** (`harness/validate_env.py`), run on every image:

| Check | Pass rule |
|---|---|
| identity | a file from the requested commit hashes the same inside the image |
| no history | there is no `/app/.git` |
| collection | the target tests collect without errors |
| stability | every test gets the same outcome across repeated fresh containers |
| baseline | every failure is recorded in a manifest, never hidden |

**Real problems this caught:**
- **Untranslated messages.** Tests asserted German text, but CI compiles translations and my first image didn't. I fixed the Dockerfile rather than the test.
- **A yanked dependency.** Resolving as of one commit's date only found a release that PyPI later yanked for a data-loss bug. I added a documented, per-commit override to the bug-fix release.
- **Unexplained query-count failures.** Two query-count budget tests failed identically on every run. The cause is not yet explained, so they were recorded and excluded from grading, never forced green.

---

## 3. How candidates were found

**Mining** (`harness/mine_prs.py`). pretix squash-merges every PR, so one commit is one PR. Scanning 1,879 commits since June 2025:

| Dropped because | Count |
|---|---|
| not a PR (no `(#N)` in the title) | 1,124 |
| not a feature (fix / bump / translations / revert …) | 256 |
| no test files | 371 |
| fewer than 60 added test lines | 88 |
| fewer than 3 product files | 9 |
| product change under 120 or over 2,500 lines | 10 |
| **kept** | **21** |

**Behaviour proof** (`harness/screen_pr.py`). For each candidate, the PR's own tests run 3 times without its product change and 3 times with it, each in a fresh container. Every test lands in exactly one bucket:

| Bucket | Meaning | Graded? |
|---|---|---|
| `must_turn_green` | red before, green after, on every run | yes: this is the feature |
| `must_stay_green` | green before and after, on every run | yes: no regressions |
| `broken_by_gold` | green before, red after | the PR is rejected |
| `flaky` / `excluded` | unstable, or red for other reasons | never graded |

Each `must_turn_green` test is also labelled with **why it was red before**: feature missing, wrong value, could not import, or infrastructure. Infrastructure reasons reject the task. That ensures a task fails for the right reason.

**Result across the 21 candidates:**
- **12 usable**;
- **7 too thin** (fewer than 5 graded new tests);
- **2 rejected**:
  - one had only browser tests, which the project's CI runs separately;
  - in the other, the whole test suite could not even load without the feature, so existing tests couldn't be separated from new ones.

---

## 4. From single PR to multi-PR

**Probe 1: #6115, reusable-media exchange at check-in.**
- **Result:** GPT-5.5-high passed 86 of 87 new tests in **5.5 minutes**.
- **Fairness:** the single miss was *my* fault. Two checks applied at once and the instruction didn't say which wins. I fixed the instruction.
- **Lesson:** the more precisely a ticket states the contract (which fairness requires), the more a single contained feature becomes spec-to-code translation. That was too easy.

**Probe 2: #5019, order-level tax rounding, the hardest single PR.** I chose it for its size (25 files, 5 layers), money logic, and 692 existing tests at risk.
- **Result:** GPT-5.6-sol scored **0.0** (28 of 33 new tests). Its rounding algorithm passed all 13 unit tests.
- **Where it failed:** only in *applying* the rule consistently: the order split, web checkout placement, and a one-cent cart total.
- **The trace:** it never ran checkout tests with rounding switched on, and it reported "checkout validated" anyway.

**The insight.** Difficulty that survives a precise ticket comes from **one set of rules that must hold across many code paths, in features that build on each other.** So I grouped the usable PRs into families by shared code and dependency (`harness/chain_check.py`) and tested which ones can be removed together.

The tax family was the strongest:
- **#4962** (default tax rule and fee taxation) → **#5565** (safe event cancellation) → **#5019** (tax rounding);
- #4962 and #5019 share 10 files;
- fees taxed by #4962 are rounded by #5019, and cancellation fees flow into #5565's refund preview.

---

## 5. How the chain task is built

**Removal, not forward stacking.** Replaying the PRs forward from before the first one conflicts, because the later PRs depend on unrelated commits merged in between. Instead I start at the newest PR's commit (#5019) and remove all three features, newest first. That keeps every unrelated commit in place.

**Hand work, all documented:**
- **1 product-code conflict.** A view block #5565 added had later been re-indented. I restored the pre-#5565 view.
- **2 test-file conflicts.** Resolved to the pre-feature side, so the base contains no tests for the removed features.
- **Migrations.** I removed the 3 migrations the features added and re-pointed one later migration (`0284`) to its previous parent.
- **Documentation.** The PRs' docs were also reverted, so the repository's docs don't describe the answer.

**The check that matters:** the restored tree is **byte-identical to the real #5019 commit**. The gold patch is exactly the difference between the base and the real commit: 42 files, +1,763 / −405.

**Chain rules** (`harness/chain_members.py`):
- at least 4 graded new tests: **517** ✅
- every member owns at least 2: #4962 owns **17**, #5565 **23**, #5019 **32** ✅
- no member owns 90% or more ✅

The other 445 graded new tests are older checkout, order and API tests. Their shared test setup creates tax rules with the new `TaxRule.default` field, so they only pass once Part A is built correctly.

**Build.** The base commit only exists locally, so the task Dockerfile fetches the real public #5019 commit by sha, applies `environment/feature_removal.patch`, and deletes the patch in the same step.

---

## 6. The instruction

The instruction is written from scratch as one product ticket. Rules I followed:

- **State everything that can't be guessed.** Exact names, fields, settings, status codes, error texts, which rule wins when two apply, rounding direction (half-up), and worked cent-level examples.
- **Hide everything that can be found.** No file paths, no function names of existing code, no PR numbers or commits, and no "how to implement".
- **Name internal code only when a test calls it directly.** For example, a renamed internal method and a new `event=` argument are named because graded tests call them.
- **Leave out untested behaviour.** The emailed confirmation code from #5565 isn't graded, so it isn't asked for.
- **One coherent feature**, told the way a product team would write it.

`harness/package_check.py` enforces the leak rules automatically. It also checks that every new name or literal a graded test relies on appears in the instruction.

---

## 7. Verifier design

`tests/test.sh` runs after the agent, as root, with **no network**:
1. It writes a zero reward first, so a crash still ends in a reward file.
2. It replaces `src/tests` and the pytest config with its own copy (`tests/pristine.tar.gz`).
3. It removes stray `conftest.py`, `pytest.ini`/`tox.ini` and `sitecustomize.py` files, plus any new top-level entry in `/app/src` (for example a `pytest.py` that shadows the real one).
4. It runs the graded test files with the config pinned (`-c setup.cfg`).
5. `tests/grade.py` writes `reward.json`:

| Field | Meaning | Maps to the brief's |
|---|---|---|
| `must_turn_green` | fraction of the 517 new-behaviour tests passing | functional correctness |
| `must_stay_green` | fraction of the 1,430 existing tests still passing | constraint satisfaction |
| `integrity` | 0 if product code gained references to pytest internals | robustness / anti-cheat |
| `overall` | **1.0 only if all of the above are perfect**, otherwise 0.0 | overall |

`reward.json` holds numbers only. The list of failing test ids goes to `details.json`, for analysis.

Grading is **outcome-based**. It runs pretix's own tests against the agent's code, never greps the agent's source to judge correctness, and accepts any implementation that behaves correctly. The one exception is the tamper scan, which only detects cheating.

---

## 8. Pre-QA checks

Every task goes through these stages in order. A stage passes only on evidence that can be re-run. The results for this task are in `evidence/gates/`.

| # | Stage | Question | Checks | Why it exists | Result |
|---|---|---|---|---|---|
| 1 | **Box check** | Is the environment trustworthy? | identity, no `.git`, collection, repeat stability, recorded baseline | Without it, no later result means anything | ✅ |
| 2 | **Behaviour proof** | Does the task test the feature, fail for the right reason, and not flake? | 3 + 3 fresh runs; F2P/P2P buckets; red-before reasons; broken-by-gold; flaky exclusion | Stops tasks that are already solved, tasks red for environment reasons, and flaky grading | ✅ 517 / 1,430, 0 flaky |
| 3 | **Chain rules** | Does every PR in the chain matter? | at least 4 total, at least 2 per member, no member at 90% or more | Stops a "chain" that is really one PR with passengers | ✅ |
| 4 | **Package check** | Is the folder complete and leak-free? | required files; `task.toml` fields; Dockerfile policy (digest pin, no `:latest`, no tests/solution in the image, no `curl \| sh`); gold touches no tests; no secrets; size; no PR, commit, file or test names in the instruction; no implementation-only names; contract coverage | Structure mistakes and hint leaks are the most common causes of unfair or trivial tasks | ✅ 9/9 |
| 5 | **Harbor proof** | Does the packaged task behave under the real runner? | `harbor run -a oracle` → 1.0; `-a nop` → 0.0; no errors | Stages 1–4 use plain Docker; this proves Harbor sees the same thing | ✅ |
| 6 | **Hardening: attacks** | Can an agent cheat? | 7 attacks run as the unprivileged `agent` (below). Each must land or be refused by the OS, and still score 0. The oracle must still score 1.0 and nop 0.0. | A hard task is worthless if gaming the grader is easier than doing the work | ✅ all blocked |
| 7 | **Hardening: network** | Is the agent really offline except for its model? | A probe run under the real agent policy. GitHub (site, API, source zip, git) blocked; PyPI blocked; other sites blocked; model APIs reachable; runs as `agent` | The real PRs are public, so an agent with internet could copy them | ✅ |
| 8 | **Model runs** | Does a frontier model fail, and fairly? | trace analysis per run; every failed test mapped to a ticket requirement; infra failures excluded | Separates capability failures from task mistakes | see §9–§10 |

**The 7 attacks** (`harness/redteam.py`):

| Attack | What it tries | Why it scores 0 |
|---|---|---|
| overwrite tests | replace every graded test with `assert True` | the verifier restores its own test tree |
| write reward | write `reward.json = 1.0` | the agent user can't write there (the OS refuses), and the verifier writes the reward last anyway |
| skip conftest | add a conftest that skips every test | removed with the restored test tree |
| shadow pytest | add `/app/src/pytest.py` that fakes an all-green run | new top-level entries are deleted |
| root conftest | add `/app/src/conftest.py` that rewrites failures to passes | stray conftest files are deleted |
| ini override | add `pytest.ini` that selects no tests | deleted, and the config is pinned with `-c` |
| product hook | patch pytest's reporting from inside pretix | the tamper scan sets integrity to 0, which forces overall to 0 |

My first version of this check reported everything as blocked even though no attack had actually run (a quoting bug). Since then, each attack must be *proven* to have taken effect before its block counts.

---

## 9. Model runs and failure analysis

All runs used Harbor 0.23.0. The harness CLIs are pinned in the image (Codex 0.158.0, Claude Code 2.1.284), and the models are the ones recorded on every trajectory step. Raw material is in `evidence/runs/`.

| Model | Harness / route | Instruction | Reward | New tests | Existing broken | Time | Steps / tools | Agent test runs |
|---|---|---|---|---|---|---|---|---|
| **GPT-5.5**, reasoning effort high | Codex, via OpenRouter | final | **0.0** | 494 / 517 | 0 | 17.1 min | 155 / 200 | 29 |
| **Claude Opus 4.7** | Claude Code, via OpenRouter | final | **0.0** | 503 / 517 | 0 | 24.7 min | 182 / 177 | 30 |
| GPT-5.6-sol, reasoning effort high | Codex, direct | earlier draft | **0.0** | 507 / 517 | 4 | 18.9 min | 184 / 178 | 20 |

### Where each model failed (graded new tests, grouped by instruction requirement)

| Requirement | GPT-5.5 | Opus 4.7 | GPT-5.6-sol |
|---|---|---|---|
| C: rounding algorithm | **8** (corrected every line instead of stopping once the difference was used up; currencies without decimals; reverting corrections) | 1 (switching modes didn't undo earlier corrections) | 0 |
| C: web checkout | **4** | **4** | **1** |
| C: API order creation | 2 | 2 | 1 *(`simulate` shape, unclear, not counted)* |
| C: order changes and split | 2 | 2 | 1 |
| C: payment method change | 0 | 1 | 0 |
| A: default tax rule, copy and clone | **5** | 2 | 0 |
| A: cancellation-fee split | 1 | 1 | 0 |
| B: dry-run refund total | 1 | 1 | 5 *(draft wording, not counted)* |
| Existing behaviour broken | 0 | 0 | 4 admin pages (`must_stay_green`), plus 2 older API cancellation-fee behaviours |

### What went wrong, and why these are capability failures

1. **Consistency across paths.** Every model built the rounding rules, then failed to apply them everywhere the ticket lists them.
   - The web-checkout sum-by-net test failed for all three.
   - The order-split test failed for all three.
   - The ticket names each of these places explicitly (Part C, requirement 12).
2. **Checking only part of the work.** Each model skipped graded test files that were in `/app` and would have exposed its bugs:

   | Model | Skipped |
   |---|---|
   | GPT-5.5 | the checkout and rounding unit tests |
   | Opus 4.7 | the checkout tests |
   | GPT-5.6-sol | the admin event tests, which is where it broke 4 existing pages |

   All three ran many tests: 20–30 runs each. They tested *their own* changes and the default mode, not the stated behaviour end to end.
3. **Claiming more than was verified.** Every final message reports the work as complete.
   - GPT-5.6-sol wrote "Validation completed" while its checkout and split behaviour was broken.
   - Opus 4.7 wrote that event copying "preserves the source event's default rule", while its clones ended up with two tax rules.
4. **Long horizon, with no timeouts.** Each run took 17–25 minutes and about 155–185 steps, changing 13–18 product files across 6–7 layers. None hit the 2-hour limit, so the failures are not about time.

---

## 10. Fairness audit

**Solvable.**
- The oracle scores 1.0, and the gold is the maintainers' own code, byte-identical to the real commit.
- Expert estimate: about 20 hours.

**Unambiguous.**
- Every graded assertion was checked against the instruction by `package_check.py` and by hand.
- Each counted failure maps to a stated requirement (§9, and `analysis.md` per run).

**Not caused by the environment.**
- The same image passes 100% with the oracle and scores 0 with nop.
- There are 0 flaky tests over 3 + 3 runs.
- The verifier runs with no network.

**Not caused by time.** Every run finished well inside the 2-hour limit.

**Mistakes I found in my own work, and fixed.**

| Found in | Problem | Fix |
|---|---|---|
| #6115 probe | The instruction didn't say which of two checks wins | The check order is now listed |
| #5019 probe | It didn't say that no payment fee applies before a payment method is chosen | That sentence was added |
| GPT-5.6-sol chain run | "Refund automatically" was wrong: the real value counts refunds under any refund mode. 5 of that run's failures came from this wording and are **not counted**. | Rewritten |
| GPT-5.6-sol chain run | The API test compares the response exactly, but the instruction didn't say which new API fields exist. 1 failure was unclear and is **not counted**. | "`tax_rounding_mode` is the only new order API field" |
| Packaging | The first package missed changed test helpers (`conftest.py`), so the oracle scored 0 | Every test-side file the PRs changed is now included, and the Harbor proof caught it |
| Grader | `reward.json` contained lists, which Harbor rejects | The lists now go to `details.json` |

The runs on the two target models used the **final** instruction, with no known ambiguity left.

**Infra failures, never counted as results** (documented in `evidence/`):
- a Debian mirror returned 403 during agent setup;
- a TLS error while downloading `nvm`;
- a credential misconfiguration in my runner.

They led to three fixes: Node.js from the checksum-pinned official release, both agent CLIs pinned in the image, and correct OpenRouter credentials in the runner.

---

## 11. Realism and economic value

This is work companies pay senior engineers for:
- **Tax on fees, and e-invoicing.** EU e-invoicing (EN 16931) requires order-level tax calculation, and cancellation and payment fees have country-specific tax rules. Ticketing, e-commerce and SaaS billing teams face this whenever they sell into regulated markets.
- **Refund safety.** Bulk cancellations move real money, so a reliable "how much will this refund?" preview is a genuine operations requirement.
- **Consistency is the real cost.** Implementing a rounding function takes an hour. Getting it right in every cart, checkout, API, payment-change and order-edit path, without breaking 1,430 existing behaviours, is the multi-day part. That's exactly where the models failed.

The gold change is 42 files and about 2,200 lines, written by pretix's maintainers over three PRs. The task reflects real, paid product engineering on a production codebase.

---

## 12. Provenance and licences

**Codebase.** pretix is © pretix GmbH and contributors and licensed under **AGPL-3.0** with additional terms. It is used unmodified from the public repository at commit `3e972eddbf117a17da33e730f9e3fc8bf4f59306`. The task environment fetches it at build time; this repository ships only a removal patch against it.

**Taken from pretix:**
- the product code of PRs #4962, #5565 and #5019, which is the gold patch;
- their tests and the existing test suite, which are the grader.

**Created from scratch for this task:**
- the feature-removal base, including the conflict resolutions and migration re-pointing;
- the combined instruction;
- the verifier (`test.sh`, `grade.py`, restoration and anti-tamper logic);
- the hardening, the red-team and network checks;
- the packaging, and all the harness tooling (`harness/`: mining, environment building, behaviour proof, chain checks, package checks, Harbor proof, trace analysis, evidence collection);
- this report.

**This is not a port of a benchmark or a public issue.** It combines three merged PRs into a new reconstruction scenario, with a new instruction and grading.

**Tooling:** Harbor (the runner), uv, Docker, and the official Python and Node.js images, all pinned.

---

## 13. Limitations

- **One run per model on the final instruction.** The brief asks for at least 1 trial, which is met. I'd like 3–5 per model to measure a failure *rate*, but my API credit ran out.
- **The agent's final code is inferred from traces.** Failures are observed through the tests, and the reasons are inferred from traces. Capturing a diff of the agent's final code in the verifier logs is the next improvement.
- **The 445 shared tests** depend on the new `TaxRule.default` field through shared test setup. This is fair (Part A requires it), but it makes the headline count larger than the 72 tests owned by individual PRs.
- **Hand-resolved removal.** Three conflicts and one migration dependency were resolved by hand. They are documented in §5, and they are validated by the byte-identical restored tree and the oracle pass.
- **Platform.** The images were built and validated on linux/arm64 (Apple Silicon). The Dockerfile supports amd64, with checksums for both, but the evidence runs were arm64.
- **Harbor version.** The non-root agent user and the network allowlist need Harbor ≥ 0.23. On 0.1.x they are ignored, and the task still runs but is less hardened.
- **Network route.** The model runs went through OpenRouter, so `openrouter.ai` is on the agent allowlist next to the OpenAI and Anthropic APIs.

---

## 14. Reproduction

```bash
# the task (Harbor >= 0.23)
harbor run -p ./pretix-tax-compliance-chain -a oracle                    # expect 1.0
harbor run -p ./pretix-tax-compliance-chain -a nop                       # expect 0.0
harbor run -p ./pretix-tax-compliance-chain -a codex -m openai/gpt-5.5 --ak reasoning_effort=high
harbor run -p ./pretix-tax-compliance-chain -a claude-code -m anthropic/claude-opus-4.7
harbor view ./jobs
```

```bash
# how this task was produced (from the repository root)
python3 harness/mine_prs.py --repo output/repos/pretix --since 2025-06-01 --out output/mining/candidates.json
python3 harness/screen_all.py --parallel 2
python3 harness/chain_check.py 5019 5565 4962
python3 harness/chain_members.py output/screens/chainA 4962 5565 5019
python3 harness/pack_task.py --screen chainA --prs 4962 5565 5019 \
    --upstream 3e972eddbf117a17da33e730f9e3fc8bf4f59306 --slug pretix-tax-compliance-chain
python3 harness/package_check.py tasks/pretix-tax-compliance-chain
python3 harness/redteam.py       tasks/pretix-tax-compliance-chain
python3 harness/network_check.py tasks/pretix-tax-compliance-chain
python3 harness/harbor_proof.py  tasks/pretix-tax-compliance-chain --repeat 3
python3 harness/run_model.py     tasks/pretix-tax-compliance-chain --agent codex --model openai/gpt-5.5 --via openrouter
python3 harness/run_model.py     tasks/pretix-tax-compliance-chain --agent claude-code --model anthropic/claude-opus-4.7
python3 harness/collect_evidence.py pretix-tax-compliance-chain --screen chainA
```

API keys are read from a local, git-ignored `.env` and passed to Harbor only through the process environment. They are never written to job files, which were scanned before being copied into `evidence/`.
