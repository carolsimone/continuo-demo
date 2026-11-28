# continuo-demo

A reference **producer** for [continuo](https://github.com/carolsimone/continuo). It owns several projects (dbt projects and one Python project), builds their images, and releases them through continuo from CD: continuo checks each release as a candidate release and promotes it once it passes. It is the worked example of how a team's CD integrates with continuo, written in continuo's glossary words so a team can copy it as it is.

## Reference implementation of the public "loading releases" interface

This repo is the **reference external integration** for continuo's public release-loading contract. It is a deliberate, independent reimplementation of that contract: it shares **no code** with continuo internals — no Go packages, no shared client library. Everything here (the `POST /api/v1/releases` body, the bootstrap detection) is rebuilt from the contract alone. That duplication is the point: it proves the contract is self-describing enough for an outside team to integrate against without reading continuo's source.

The authoritative contract is continuo's public `/api/v1` API (`POST /api/v1/releases`, `GET /api/v1/releases/{id}`, `GET /api/v1/live-release`), documented in the continuo repo's `deploy/README.md` under "Releasing from CI (GitHub Actions)". If this README and that documentation ever disagree, the continuo docs are authoritative — open an issue against continuo or this repo.

## What it does

Each project is either a **dbt project** (`dbt_project.yml`) or a **Python project**, released with kind `python` (ODCS data contracts in `contracts/<table>.odcs.yaml` instead — see `projects/project-py/`). On every push to `projects/**` (or manual dispatch), `.github/workflows/release.yml` detects which kind the single changed project is and adapts:

1. **Builds + pushes** the one changed project's image to Docker Hub as `<DOCKERHUB_USERNAME>/<project>:<short-sha>` (+ `:latest`), for both `linux/amd64` and `linux/arm64`. The name/tag is the contract: continuo's execution-controller runs each task of a dbt project in `<DOCKERHUB_USERNAME>/<project>:<image_tag>`. Both architectures are built because the *pulling cluster* decides which one it needs, and a single-architecture image is unpullable everywhere else — an arm64 node rejects an amd64-only manifest with `no matching manifest for linux/arm64`, which is what an Apple Silicon laptop running a local cluster hits. Each project image is **self-contained** — there is no shared base image, so a single-project change rebuilds only that project. Validation runs in a continuo-owned image, so team images carry no validator.
2. **Python projects only**: `continuo-runtime lint`/`validate`/`pack` (from [continuo-python-runtime](https://github.com/carolsimone/continuo-python-runtime)) run around the image build. Before it, `lint` checks the scripts and `validate` checks the contracts against the install's postgres dialect; after the image is pushed, `pack` writes the ODCS bundle (the contracts as written, the hashes of each node's script and shared code, and the packages installed in the pushed image). The CLI version is the one the project's `FROM` line names, and the workflow checks that the installed CLI is that version. The bundle is uploaded to `s3://continuo-dev/<project>/<release_id>/odcs-bundle.json` before the release is posted — continuo does no existence check, so the upload must land first.
3. **Drives the release** (`scripts/release.sh`): calls continuo's public API with a bearer token — reads `GET /api/v1/live-release` to detect bootstrap, `POST`s the candidate to `/api/v1/releases`, then **polls `GET /api/v1/releases/{id}` to a terminal status — failing the job on `rejected` or `superseded`**. For a dbt project, continuo compiles the changed project and validates the full topology before promoting; for a Python project, continuo parses the uploaded `odcs-bundle.json` instead — there is no compile leg.

4. **The ontology.** The demo is its own ontology repository: `ontology/ontology.yaml` is released as the project `ontology`, with kind `ontology`, by the `release-ontology` job of `release.yml`. A push that changes that file uploads it to `s3://continuo-dev/ontology/<release_id>/ontology.yaml` and posts the release, with `release_id` `rel-<sha>-<run>-ontology`. When the same push changes a project, the project is released first and the ontology only after the project's release was promoted; two changed projects are still refused, since the ontology is not a project folder. To release the ontology again by hand, for example after its job failed or never started, run the `release` workflow (Actions, Run workflow, or `gh workflow run release.yml -f project=ontology`) with `project` set to `ontology`: it releases `ontology/ontology.yaml` at the current `main`, and no project. `force_bootstrap` and `rebaseline` do not apply to it. The pull request that changes the file runs `continuo-contracts ontology check ontology/ontology.yaml` (the `ontology-check` job of `ci.yml`), and every project is checked against the ontology file of the same checkout: `dbt-lite-check` and `python-checks` pass `--ontology ontology/ontology.yaml`. A pull request that changes the file is checked against every project, not only the one it changes (the `ontology-projects-check` job): a property that a project binds, renamed or removed in the file, fails there and not on dev after the merge. continuo checks the contracts of the projects the ontology declares under `principals.projects`, and no others.

In CI the bearer token is the workflow's GitHub Actions OIDC token: the release job sets `permissions: id-token: write`, `release.sh` requests a fresh token for each API call (they expire within minutes) with the origin of `CONTINUO_URL` as its audience, and the repository must be bound to the project in continuo's `ciAuth.bindings`. There is no stored credential to rotate. See [Releasing locally](#releasing-locally) for running `release.sh` from a workstation with your own token.

### The release contract (what `scripts/release.sh` sends)

continuo models a release as a **single changed project**. The request body is:

```json
{"release_id": "rel-<sha>-<run>", "project": "project-3", "image_tag": "<sha>", "bootstrap": false, "repo": "<owner>/<repo>", "commit_sha": "<full-sha>"}
```

For the ontology the body is `{"release_id": "rel-<sha>-<run>-ontology", "project": "ontology", "image_tag": "<sha>", "bootstrap": false, "repo": "<owner>/<repo>", "commit_sha": "<full-sha>", "kind": "ontology"}`: there is no image, and `image_tag` is the short sha of the commit. For a Python project the body gains one field, `"kind": "python"`, and `image_tag` is a full pullable registry ref rather than a bare tag (continuo runs a Python project's `image_tag` verbatim; a dbt `image_tag` is composed into a pull ref by continuo itself):

```json
{"release_id": "rel-<sha>-<run>", "project": "project-py", "image_tag": "docker.io/<user>/project-py:<sha>", "bootstrap": false, "repo": "<owner>/<repo>", "commit_sha": "<full-sha>", "kind": "python"}
```

- `project` and `image_tag` are **single values**, not maps. `repo` and `commit_sha` identify the source push (`github.repository` / `github.sha`). For a CI token continuo takes both from the token, so they must equal the token's values or be omitted (a different value is a `403` `claim_mismatch`); a person calling with their own token must send both. For a dbt project the image tag travels in this body, not in S3.
- continuo replies `202 Accepted` with `{"release_id": "...", "status": "..."}`.
- The script then polls `GET /api/v1/releases/<release_id>` until `terminal` is true: `promoted` (success), `rejected` (failure; `reject_reason` and `reject_detail` say why) or `superseded` (failure). Every answer carries `ui_url`, the release's page in the dashboard. For a dbt release continuo reconstructs the full manifest set from the production pointers, with manifests produced by continuo's internal compile leg. For a Python project's release it reads the `odcs-bundle.json` already uploaded to S3 (step 2 above).

### First run = bootstrap

`release.sh` sets `bootstrap:true` automatically when `GET /api/v1/live-release` reports no live release (`live_release_id` empty). A bootstrap release **promotes without validation** — necessary because, against an empty production, normal validation rejects every cross-project upstream as new. Every subsequent run posts `bootstrap:false` and goes through validation. (Bootstrap promotes whatever topology it carries, so the first push must be a trusted one.) Bootstrapping a project is an operator action: a CI token may bootstrap only when the repository's `ciAuth.bindings` entry sets `allowBootstrap: true`, and a binding without it answers `403` `bootstrap_not_allowed`. The usual setup is to bootstrap each project once with an operator token (see [Releasing locally](#releasing-locally)) and leave `allowBootstrap: false` for CI.

#### Re-baseline after continuo changes its hash formula

When continuo changes its hash formula, every stored hash stops matching. A normal release would then validate the whole estate and reload every seed. continuo's upgrade notes ask for one `rebaseline` release per project instead, while producers freeze their merges.

Run it once per project, one run at a time (the concurrency group keeps one waiting run):

```bash
gh workflow run release.yml -f project=<project> -f rebaseline=true
```

The body then carries `"bootstrap": true, "rebaseline": true`. A rebaseline is a bootstrap, so the repository's binding must allow bootstrap, or you use an operator token. A continuo older than rebaseline releases answers `400` with `unknown field(s): rebaseline`, and nothing is released.

## Repo layout

```
projects/        # one directory per project.
                 #   dbt project: dbt_project.yml, profiles.yml (schema: analytics),
                 #     macros/ (generate_schema_name), models/, seeds/, Dockerfile
                 #     (plain dbt, every dbt package pinned)
                 #   Python project: contracts/<table>.odcs.yaml, scripts/*.py, Dockerfile
                 #     (FROM ghcr.io/carolsimone/continuo-python-runtime-<engine>:v<version>)
scripts/         # repo CD/utility tooling: release.sh, image_pins.py (reads the runtime
                 #   version and checks the dbt pins of a project Dockerfile),
                 #   gen_users.py, gen_transactions.py,
                 #   gen_fx_rates_eur.py, gen_marketing_spend.py, gen_operational_costs.py
                 #   Seed generators are ordered: gen_users -> {gen_marketing_spend,
                 #   gen_transactions -> gen_fx_rates_eur}; gen_operational_costs is independent.
ontology/        # ontology.yaml: the company ontology this repository releases (project `ontology`)
.github/workflows/   # release.yml (releases), ci.yml (pull request checks)
```

The projects fall into three groups. `core`, `finance`, and `marketing` are clean dbt example workloads — the part to read if you're modelling how your own dbt producer integrates. `project-1`, `project-2`, and `project-3` are copied from continuo's e2e fixtures: they carry deliberate cross-project dependencies (including a project-2 ↔ project-3 cycle) and probe / failure nodes whose only purpose is to exercise continuo's validation and reject paths. They are testing scaffolding, not a modelling example. `project-py` is the reference **Python project** (kind `python`), its data contracts written in ODCS as `contracts/<table>.odcs.yaml` — `analytics.py_daily_kpis` reads `core`'s `analytics.daily_transactions` table and rolls it up into a daily count/total, and `analytics.demo_orders_csv` is a contract-only `python-csv` node that loads a demo CSV export straight from object storage (no script), the worked example of integrating a Python project instead of a dbt one. All projects materialize into the **`analytics`** schema.

### Cross-project references (important)

A continuo producer's projects are **separate dbt projects**, and dbt's `{{ ref() }}` only resolves nodes *within one project*. So a model that depends on a table built by **another** project cannot `ref()` it — that fails at `dbt compile` with `depends on a node named '…' which was not found`. The convention:

- **Within a project** (depends on a seed/model in the same project): use `{{ ref('name') }}`. dbt resolves it and orders the build.
- **Across projects** (depends on a table another project produces in the shared `analytics` schema): reference it by its **raw schema-qualified name** — `FROM analytics.table_a` — never `ref()`. continuo sequences the cross-project build itself (through the release check of each candidate release and the production pointers); dbt never needs the upstream in its own graph.

This is the easiest integration mistake to make — even an automated fixer once "corrected" a cross-project `FROM analytics.table_a` into `{{ ref('table_a') }}` and broke the build.

## Required CI secrets and variables

Configure these in the repo's Actions settings before the workflow can run. The release call needs no secret: it authenticates with the workflow's OIDC token, which works once the repository is bound in continuo's `ciAuth.bindings`.

| Name | Kind | Purpose |
|---|---|---|
| `DOCKERHUB_USERNAME` | secret | Docker Hub user; **must match** the username continuo's execution-controller uses to pull the images of its Jobs. |
| `DOCKERHUB_TOKEN` | secret | Docker Hub push token. |
| `CONTINUO_URL` | variable | Origin of continuo's ui (`scheme://host[:port]`, no path), where `scripts/release.sh` calls the public `/api/v1` API. The release step fails when it is empty. |
| `HETZNER_S3_ACCESS_KEY_ID` | secret | Python projects and the ontology only: credential for uploading `odcs-bundle.json` and `ontology.yaml` to the Hetzner object store. |
| `HETZNER_S3_SECRET_ACCESS_KEY` | secret | Python projects and the ontology only: secret for the same uploads. |

## Releasing locally

`scripts/release.sh` runs from a workstation the same way it runs in CI, with your own bearer token instead of the workflow's: set `CONTINUO_URL` to the origin of continuo's ui and `CONTINUO_TOKEN` to an OIDC ID token for a person with the operator role (continuo's `deploy/AUTH.md`, "Bearer tokens", shows how to get one from the bundled Dex). A person's token must send `repo` and `commit_sha`, so set `REPO` and `COMMIT_SHA` too.

```bash
export CONTINUO_URL=http://localhost:8090   # kubectl -n continuo port-forward svc/ui 8090:8090
export CONTINUO_TOKEN=<operator id token>
RELEASE_ID=rel-local-$(date +%s) PROJECT=project-3 IMAGE_TAG=<tag> \
  REPO=<owner>/<repo> COMMIT_SHA=$(git rev-parse HEAD) bash scripts/release.sh
```

An operator token may also bootstrap a project (`FORCE_BOOTSTRAP=true`, or automatically when production has no live release). `REBASELINE=true` sends a rebaseline.

## Local checks

```bash
shellcheck scripts/release.sh

# Every script test, as the scripts job of ci.yml runs them: release.sh against a stub of
# continuo's release API (needs curl and jq), the image pins, the workflows, the glossary words
# this repository uses and the seed generators:
uvx pytest==9.1.1 scripts/tests

# A dbt project: check that its Dockerfile pins every dbt package.
python3 scripts/image_pins.py check-dbt projects/core

# A dbt project: continuo's lite check, the dbt-lite-check job of ci.yml. dbt runs from a
# Python 3.12 virtualenv built from the pins of the project's Dockerfile. continuo-contracts
# needs Python 3.14, so it is a separate tool, and the check is given that dbt with --dbt.
# Install the CONTINUO_CONTRACTS_VERSION that ci.yml sets in its env. Passing the check does not
# guarantee the release: the release runs more checks than this one.
uv venv --python 3.12 /tmp/dbt
uv pip install --python /tmp/dbt/bin/python $(python3 scripts/image_pins.py dbt-requirements projects/core)
uv tool install --python 3.14 "continuo-contracts==0.5.0"
continuo-contracts dbt check projects/core --dbt /tmp/dbt/bin/dbt --ontology ontology/ontology.yaml

# The ontology file: the check every ontology repository runs, the ontology-check job of ci.yml.
continuo-contracts ontology check ontology/ontology.yaml

# A Python project: lint/validate/pack with continuo-runtime. Install the version
# the project's FROM line names, the same one the workflows install:
v="$(python3 scripts/image_pins.py runtime-version projects/project-py)"
uv tool install "continuo-python-runtime==${v}" || \
  uv tool install "git+https://github.com/carolsimone/continuo-python-runtime@v${v}"
continuo-runtime lint projects/project-py/scripts/
continuo-runtime validate projects/project-py/contracts/ --dialect postgres --project project-py --ontology ontology/ontology.yaml
# Locally there is no pushed image to read the packages from, so pack takes an empty
# package listing, as the dry run in ci.yml does (the release passes --image instead).
echo '{}' > /tmp/packages.json
continuo-runtime pack projects/project-py/contracts/ --project project-py --repo-root projects/project-py --dialect postgres --image-packages /tmp/packages.json --out /tmp/odcs-bundle.json
```

## License

[CC0 1.0 Universal](LICENSE) — this is example code, dedicated to the public
domain. Copy it, adapt it, ship it; no attribution required.
