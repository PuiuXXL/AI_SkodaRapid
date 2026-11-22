# CI repair and local validation — 22 November 2026

## Observed failures

The investigation used actual GitHub Actions logs, rather than treating every failing badge as an integration-test failure.

| Workflow | Evidence | Cause |
| --- | --- | --- |
| Core | [Run 44998923108](https://github.com/PuiuXXL/AI_SkodaRapid/actions/runs/44998923108) | The job installed only P2 dependencies. Loading the assistant boundary imported `assistant.tts`, then failed because `edge_tts` was missing. This disabled the assistant and caused 63 test failures. |
| Perception | [Run 44997380238](https://github.com/PuiuXXL/AI_SkodaRapid/actions/runs/44997380238) | Contract tests instantiated core, but the job installed only P1 dependencies. Two tests failed because FastAPI was missing. |
| Integration | [Run 44998923106](https://github.com/PuiuXXL/AI_SkodaRapid/actions/runs/44998923106) | This run already passed. The end-to-end tests also passed locally during this repair. |

## Changes

- Core installs both P2 and P3 runtime requirements, checks dependency consistency and verifies core/assistant/TTS imports before tests.
- Perception installs P2 requirements alongside P1 because its selected contract tests instantiate core.
- Dependency cache keys and path filters include these cross-module inputs. Integration PRs also react to `pyproject.toml`.
- Local PowerShell scripts detect a missing Python environment and command failures. Advisory style reports match GitHub's `continue-on-error` behaviour; runtime lint and test failures remain blocking.
- The local core job includes the same runtime-import preflight.
- Optional NVIDIA telemetry loads its binding dynamically, so a CPU-only environment does not require an NVIDIA import during static analysis. The driver/passenger head-answer patch has an explicit JSON dictionary type, avoiding incompatible nested-dictionary inference across mypy versions.
- Coverage gates remain **83% perception**, **93% core/shared/simulator** and **70% assistant**. No tests were removed or assertions relaxed.

## Local results

Windows, Python 3.11.9; separate coverage data files per suite to avoid results overwriting one another.

| Check | Result |
| --- | --- |
| Core workflow test selection | 420 passed; coverage **95.55%** |
| Perception + contract tests, without models/cameras | 448 passed, 4 skipped, 5 deselected; coverage **85.65%** |
| Assistant | 332 passed; coverage **70.54%** |
| End-to-end integration | 2 passed; real core server and spawned synthetic perception workers |
| Dashboard production build | Passed, including TypeScript |
| Dashboard rendering/contract tests | 24 passed |
| Browser voice unit tests | 22 passed |
| Perception Ruff and blocking core/assistant Ruff checks | Passed |
| Mypy | Passed: 98 source files, mypy 1.15.0 |
| Dependency consistency | `pip check` passed |
| Changed perception telemetry/modules regression selection | 47 passed, 1 deselected |
| Documentation / presentation | README local links, PPTX XML, ZIP integrity and internal relationships passed |

Hardware/model tests require their own model files, camera or recorded sessions. The synthetic integration run verifies transport, lifecycle and command handling, rather than model accuracy.

PowerShell scripts were parsed for syntax. The frontend build reports existing Motion directive and bundle-size warnings without failing.

Windows Application Control blocked the binary `librt` extension used by mypy 2.4.1. The local check used the pure-Python build of mypy 1.15.0, which satisfies the repository's `mypy>=1.13` requirement. GitHub's Linux job resolves its own mypy version; it was not rerun remotely during this repair.

## Reproduce

Follow the root [README](../README.md) to install the module dependencies. Then run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/ci_all.ps1
```

For the repaired boundary only:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/ci_all.ps1 -Only core,integration
```

Local results validate the working tree. A new GitHub Actions run is still required after committing and pushing these changes; these results do not assert that an unpushed commit has passed remote CI.
