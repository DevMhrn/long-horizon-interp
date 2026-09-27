# Quality gates

Every candidate goes through these stages in order. A stage passes on evidence I can re-run, never on my judgement alone.

| # | Stage | Question it answers | Script | Status |
|---|---|---|---|---|
| 1 | **Box check** | Is the environment trustworthy? | `validate_env.py` | built |
| 2 | **Behavior proof** | Does the PR really create the behavior the tests check, and is the task red for the right reason? | `screen_pr.py`, `screen_all.py` | built |
| 3 | **Package check** | Is the task folder complete, clean and leak-free? | `pack_task.py` → `package_check.py` | built |
| 4 | **Harbor proof** | Does the packaged task score 1.0 with the oracle and 0 with an empty agent, the same way every time? | `harbor_proof.py` | built |
| 5 | **Hardening** | Can an agent cheat? Is the agent really cut off from the internet? | `redteam.py`, `network_check.py` | built |
| 6 | **Hardness sits** | Does a frontier model fail it for real, repeatedly? | Harbor runs | planned |

## 1. Box check (per base commit)

| Check | Pass rule |
|---|---|
| identity | a file from the requested commit hashes the same inside the image |
| no_history | no `/app/.git` |
| collection | the target tests collect without errors |
| stability | same outcome for every test id across repeats in fresh containers |
| baseline | every failure is recorded in the manifest, never hidden |

## 2. Behavior proof (per PR)

The PR's own test files run in fresh containers, 3× without the gold patch and 3× with it.

| Bucket | Meaning | Graded? |
|---|---|---|
| `must_turn_green` | red before, green after, on every run | yes: the new behavior |
| `must_stay_green` | green before and after, on every run | yes: nothing else broke |
| `broken_by_gold` | green before, red after | reject the PR |
| `excluded` | red after for other reasons | never |
| `flaky` | outcome changed between runs | never |

Each `must_turn_green` test is also labelled with **why it was red before**:
- `missing_feature`: import, attribute or field errors, missing endpoints
- `behavioral`: an assertion on a wrong value
- `not_collected`: the test file could not even import
- `infra`: network, disk, a crashed worker

Verdicts:
- `ok`: at least 5 `must_turn_green`, nothing broken, no infra reasons, no dependency changes
- `thin`: 1–4 `must_turn_green`
- `bad:no_must_turn_green`
- `bad:gold_breaks_tests`
- `bad:red_for_infra_reasons`
- `bad:needs_dependency_change`: the gold patch changes packaging, which our frozen lock can't follow
- `bad:box_check_failed`
- `error:<stage>`: logged in `output/screens/pr<N>/error.txt`

## 3. Package check (per task folder)

- **Files:** `instruction.md`, `task.toml`, `environment/Dockerfile`, `solution/solve.sh` and `tests/test.sh` all exist.
- **`task.toml`:** has the metadata, timeouts, resources and network policy.
- **Dockerfile:** never copies `tests/` or `solution/`, installs apt packages with cleanup, uses no `:latest` tags and no `curl | sh`.
- **Gold patch:** touches no test files.
- **Secrets:** none, anywhere in the folder.
- **Instruction leakage:**
  - no PR number, commit sha, or file path of existing code;
  - no identifier that the gold patch introduces unless the tests need it, in which case it must be stated as part of the contract;
  - no test names, test counts, or "the fix".
- **Contract coverage:**
  - every public name or literal a graded test asserts on appears in the instruction;
  - every numbered requirement maps to at least one graded test.

## 4. Harbor proof (per task folder)

- `harbor run -a oracle` must score 1.0.
- `harbor run -a nop` must score 0.0.
- Both repeat 3 times with identical results.
- The verifier writes `reward.json` even when tests crash.

## 5. Hardening

This stage will be brainstormed separately. At minimum it covers:
- the agent runs as a non-root user;
- the graded tests are restored from a root-owned copy before grading;
- stray `conftest.py` and `pytest.py` shadows are removed;
- attack runs (overwrite tests, write the reward file, skip-all conftest) must score 0.

### What is enforced (harbor 0.23, run via uvx)

- The agent runs as the non-root user `agent` and owns only `/app`.
- **Network:** the agent phase is on an allowlist containing only the model APIs, and the verifier has no network at all.
- **Verifier:**
  - replaces `src/tests` and `setup.cfg` with its own copy;
  - removes stray `conftest.py`, `pytest.ini`/`tox.ini`, `sitecustomize.py`, and new top-level entries in `/app/src`;
  - pins the pytest config with `-c`;
  - scores `integrity` 0 if product code adds references to pytest internals.
- **`redteam.py`** runs 7 attacks, each proven to have landed or been refused by permissions. Every one must score 0, while the oracle still scores 1.0 and nop 0.0.
- **`network_check.py`** runs a probe under the real agent policy. GitHub, PyPI and other hosts must be blocked, both model APIs must be reachable, and the probe must run as `agent`.

## 6. Hardness sits

The target model runs 5 times. The task counts as hard if the model fails at least 3 of them, with oracle at 1.0 and every earlier stage green. Infra failures, such as rate limits or crashes, never count as failures.
