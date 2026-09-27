# harness

The scripts I use to find, build and check feature-reconstruction tasks. They are run from the repo root. Local clones and build output go to `output/`, which is ignored by both git and Docker.

| Step | Script | What it does | Output |
|---|---|---|---|
| 1 | `mine_prs.py` | Lists squash-merged PRs and keeps feature PRs that change enough product code and add real tests. Groups related PRs into families. | `output/mining/candidates.json` |
| 2 | `build_env.py` | Builds the repo at one exact commit into a Docker image. Uses `git archive` (no `.git`), a digest-pinned base image and a lock taken from a working container. | image + `output/envs/<tag>/` |
| 3 | `validate_env.py` | Checks the image before anything is built on it: identity, no history, collection, and stable outcomes across repeated fresh runs. Records the baseline. | `output/envs/<tag>.manifest.json` |
| 4 | `screen_pr.py` / `screen_all.py` | Runs a PR's tests with and without its product changes. Finds the tests it turns green (F2P) and the ones that stay green (P2P). | `output/screens/pr<N>/` (screen.json, must_turn_green.json, must_stay_green.json, patches, logs) |
| 5 | `pack_task.py` | Turns a screened PR into a Harbor task folder from `task_template/`: pinned env, `solve.sh` + gold patch, graded test files, `test.sh` + `grade.py` writing `reward.json`. The instruction is a hand-written DRAFT. | `tasks/<slug>/` |
| 6 | `package_check.py` | Static checks on a task folder: files, `task.toml`, Dockerfile policy, secrets, size, instruction leaks, mechanism leaks, contract coverage. | `tasks/<slug>/.package_report.json` |
| 7 | `harbor_proof.py` | `harbor run` with the oracle and nop agents, 3× each. The oracle must score 1.0 and nop 0.0 on every run. | `output/harbor/<slug>/proof.json` |

Stage definitions and pass rules: `GATES.md`.

`skills/dockerize/SKILL.md` covers the rules and steps for step 2 and 3. `env/pretix/` holds the pretix Dockerfile, the digest-pinned Python images and one committed lock per base commit (`locks/`).

```bash
git clone https://github.com/pretix/pretix.git output/repos/pretix
python3 harness/mine_prs.py --repo output/repos/pretix --since 2025-06-01 --out output/mining/candidates.json
python3 harness/build_env.py --sha <base sha> --tag pretix-env:<label>
python3 harness/validate_env.py --tag pretix-env:<label> --sha <base sha> --targets <test paths>
python3 harness/screen_pr.py --repo output/repos/pretix --sha <pr sha> --image pretix-env:<label> --out output/screens/pr<N>
python3 harness/screen_all.py --parallel 2          # every candidate: build -> box check -> behavior proof
python3 harness/pack_task.py --pr <N> --slug <slug>
python3 harness/package_check.py tasks/<slug>
python3 harness/harbor_proof.py tasks/<slug> --repeat 3
```
