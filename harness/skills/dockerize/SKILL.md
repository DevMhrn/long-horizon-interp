---
name: dockerize
description: Turn a repository at one exact commit into a pinned, reproducible Docker image that runs its test suite, as the base for building agent tasks. Use when preparing a repo environment, fixing a broken build, locking dependencies, or checking that an image is trustworthy before tasks are built on it.
---

# Dockerize a repo for task building

The output is one Docker image of the repo at an exact commit. Its tests run the same way on every machine, and it comes with a manifest that records exactly what it contains. Every task built later inherits this image's quality, so an unreliable base makes every task unreliable.

## Rules that never bend

- **Build from the exact commit, not the working tree.** Use `git archive <sha>`. The image never contains `.git`, so an agent inside it cannot mine history for the answer.
- **Follow the repo's own CI.** Its Python version, install command and test command are the source of truth. Don't guess a runtime when CI already names one.
- **Take pins from a working container, never from your head.** Build once unlocked, prove the tests run, freeze that container into `requirements.lock`, then rebuild from the lock. Remove editable and local-project entries from the freeze, install the lock first, then install the project with `--no-deps`.
- **Pin the base image by digest,** not just by tag.
- **Make results deterministic:**
  - set `TZ=UTC`, `LANG=C.UTF-8`, `LC_ALL=C.UTF-8` and `PYTHONHASHSEED=0` in the Dockerfile;
  - check the repo's pytest config for random test ordering, and turn it off or seed it.
- **Never change product code to make the environment work.** Never skip, delete or weaken a test to get a green run, and never edit result files by hand.
- **Don't put tests or solutions in the image.** They belong to the task and are added at verify time.

## When something fails, classify it before touching anything

| Class | Looks like | What to do |
|---|---|---|
| Environment | missing system library, package, env var, service, or database schema | Fix it in the Dockerfile or lock. |
| Stale test | the test imports or mocks something that has moved, and the product is fine | Leave it failing. Record it in the baseline and exclude it from grading. |
| Product defect | the traceback ends in product code | Leave it failing. Record it. Never patch it here. |
| Harness | parser, collection or isolation problem in our own scripts | Fix our scripts. |

Never rerun an identical failing command hoping for a different result. Read the error, change one thing, rerun.

## Steps

1. **Pick the commit.** For a PR-based task this is the parent of the first PR. Resolve it with `git rev-parse <sha>^` and record the full sha.
2. **Read CI.** For pretix, `.github/workflows/tests.yml`, which runs:

   ```bash
   cd src
   PRETIX_CONFIG_FILE=tests/ci_sqlite.cfg py.test tests
   ```
3. **Write `harness/env/<name>/Dockerfile`:**
   - base image pinned by digest;
   - the system packages the resolver errors actually asked for;
   - the determinism settings above;
   - install the lock, then `ADD repo.tar`, then install the project with `--no-deps`.
4. **Build.** The first run bootstraps the lock automatically.

   ```bash
   python3 harness/build_env.py --env pretix --sha <sha> --tag pretix-env:<label>
   ```
5. **Validate** in fresh containers. The run repeats 3 times by default.

   ```bash
   python3 harness/validate_env.py --tag pretix-env:<label> --sha <sha> --targets <test paths>
   ```

   It checks:
   - **identity:** the image holds the requested commit's code;
   - **no history:** there is no `.git` inside the image;
   - **collection:** the chosen tests are found without errors;
   - **stability:** every test gets the same outcome across the repeats.

   It then records the baseline in `output/envs/<tag>.manifest.json`.
6. **Accept the image only if the verdict is `ok`.** A test that isn't stable across repeats is excluded from grading, never retried until it passes.

## pretix specifics

- **Python 3.13 on SQLite** needs no database service. `PRETIX_CONFIG_FILE=/app/src/tests/ci_sqlite.cfg` is an empty file on purpose, and the SQLite defaults apply.
- **`PRETIX_DOCKER_BUILD=1`** skips the npm/Vite asset build during install. The Python test suite doesn't need compiled assets.
- **Parallel runs:** `pytest-xdist` is part of the dev dependencies, so use `-n 4`. pretix's own `conftest.py` retries a segfaulted worker once, which is a known SQLite quirk; the stability check still sees the final outcome.
- **Translations:** CI compiles translation files before testing, and some tests assert German text, so the Dockerfile runs `manage.py compilemessages`. Without it, the localized-message tests fail. That's an environment gap, not a product bug.
- **Known environment-sensitive failures at `d3151f97`:** `tests/api/test_checkinrpc.py::test_query_load` and `::test_search`. These are query-count budget tests. They pass in upstream CI but do about 10 extra settings-store reads here, and fail the same way on every run.
  - Ruled out: dependency versions (resolving with `--exclude-newer` at the commit date gives the identical lock), TZ and hash seed, compiled translations, and collected static files.
  - The root cause is not yet found.
  - They are recorded in the manifest and never graded.
- **Platform:** the image builds for the host platform by default. Pass `--platform linux/amd64` for an amd64 build (slow under emulation on Apple Silicon). The manifest records which platform was used.

## Done means

- the image builds from a clean checkout of the harness;
- the lock is committed and the Dockerfile consumes it;
- the manifest verdict is `ok`;
- the baseline counts and any known failures are recorded, not hidden.
