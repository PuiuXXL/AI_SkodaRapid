# CI

One GitHub Actions workflow per module, each triggered only by the paths it depends on (`.github/workflows/`). All
run on `ubuntu-latest` with Python 3.11 (the version `pyproject.toml` and `requirements/` target), CPU only, no
camera, no secrets. Nothing in CI needs images, video, recordings (`data/`), profiles or model files from git.

| workflow | runs when | what it checks |
|---|---|---|
| `perception` | `perception/**`, `shared/**`, `tests/perception/**`, `scripts/**`, P1 requirements | ruff, mypy (strict), shell syntax, perception tests without models / camera, coverage >= 83 % |
| `core` | `core/**`, `shared/**`, `integrations/**`, `tests/core/**`, `tests/contract/**` | ruff runtime errors (blocking) + full report (not blocking), core tests + core side of the contract tests, coverage >= 93 % |
| `assistant` | `assistant/**`, `shared/**`, `integrations/**`, `tests/assistant/**` | ruff runtime errors (blocking) + full report (not blocking), assistant tests (offline), coverage >= 70 % |
| `integration` | `perception/**`, `core/**`, `shared/**`, `tests/contract/**`, `tests/integration/**`, `docs/perception.md` | the perception <-> core contract both ways, and `perception.main` + the core server end to end |
| `dashboard` | `dashboard/**` | `npm ci`, typecheck + build, node tests |
| `perception-models` | nightly 02:00 UTC, manual | perception tests that need the real models (downloaded with `scripts/download_models.sh`, cached) |

Coverage: a markdown summary in each job's page and the XML as an artifact (`coverage-<module>`). The thresholds sit
just below today's values (perception 85 %, core 95 %, assistant 73 % on 2026-11-21): raise them when coverage grows.

Branch protection: require `perception / check`, `core / test`, `assistant / test`, `integration / perception-core`
and `dashboard / build` on `main`. With path filters a workflow that does not run reports nothing, so mark them
required only together with GitHub's "skipped counts as passed" behaviour (rulesets), or drop the filters.

## Contract tests (tests/contract)

Golden JSON messages of the perception <-> core boundary in `tests/contract/fixtures/`, made by the real code
(`python tests/contract/make_fixtures.py`):

- `p1_frame_full.json`, `p1_frame_strict.json`, `p1_frame_cameras_down.json`: PerceptionFrames from the real worker
  pipeline + `frame_builder` (synthetic features instead of camera and models);
- `p1_messages.json`: P1's acks for every command, enroll progress / done, a calibration prompt / done;
- `core_commands.json`: every command core sends, serialized with `shared.contracts`.

`test_core_reads_p1.py` (core job, needs only `shared` + `core`): P1's messages parse with P2's contract without
losing or changing a field, and core's engine takes them (`invalid_messages == 0`, the head answer, occupants,
gesture and phone arrive). `test_p1_speaks_contract.py` (integration job, needs perception): P1 still produces
messages of the golden shape, parses every command core sends, and every field P1 sends that `shared/contracts.py`
does not declare has a `CONTRACT:` line in `docs/perception.md` §9.

When a side changes the boundary on purpose: regenerate the fixtures, review the JSON diff, tell the other side.

The route file of the dashboard's location simulator is shared the same way:
`tests/contract/fixtures/dashboard_route_file.json` must equal what `routeFile(...)` produces (`npm test`) and be
accepted by P4's trip source in core (`tests/contract/test_dashboard_route.py`, run by the core job with
`tests/simulator`).

## Running the jobs locally

From the repository root, in a venv with the job's requirements (the `pip install` line of each workflow).

```bash
# perception
ruff check && mypy
python -m pytest tests/perception -m "not models and not camera" -q --cov=perception --cov-fail-under=83

# core
ruff check core shared integrations tests/core tests/contract --isolated --target-version py311 --select E9,F63,F7,F821
python -m pytest tests/core tests/contract/test_core_reads_p1.py -q --cov=core --cov=shared --cov-fail-under=93

# assistant
ruff check assistant integrations tests/assistant --isolated --target-version py311 --select E9,F63,F7,F821
python -m pytest tests/assistant -q --cov=assistant --cov-fail-under=70

# integration (perception runtime without ultralytics + requirements/p2-core.txt)
python -m pytest tests/contract -q
python -m pytest tests/integration -m slow -q

# dashboard
cd dashboard && npm ci && npm run build && npm test

# perception-models (after bash scripts/download_models.sh)
python -m pytest tests/perception -m "models and not camera" -q
```

`tests/integration` is marked `slow` (two camera processes are spawned): the root `pyproject.toml` deselects `slow`
by default, so it runs only with `-m slow`.
