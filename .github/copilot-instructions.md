# AgeMorph3D Copilot Instructions

## Repository shape

AgeMorph3D is a local-only, Windows-oriented 3D face reconstruction and visualization project:

- `backend/` is a Python 3.11 FastAPI service. Its `src/agemorph3d/` package owns configuration, model lifecycle and readiness, image validation, detection/reconstruction adapters, realtime streaming, bounded asset storage, API schemas, and research service contracts.
- `frontend/` is a native TypeScript/Vite/Three.js application (no React or Vue). `src/` contains the production studio, service client, contracts, camera/realtime state, and viewer; `research/` contains separately hosted research pages and harnesses.
- `preprocessing/`, `training/`, and `tools/` are offline, provenance-oriented research and preparation pipelines. They must not silently become part of the production runtime.
- `docs/`, `ARCHITECTURE.md`, `DESIGN.md`, `PRD.md`, `RULES.md`, `TASKS.md`, and `PROGRESS.md` document contracts, design constraints, evidence, and unfinished work. Read the relevant document before changing a subsystem.
- `data/`, `output/`, model weights, datasets, environments, logs, and generated captures are local artifacts and are ignored by Git. Do not add them to commits or use them as source-of-truth code.

The production flow is browser input -> loopback API validation -> strict model/license readiness -> detection and reconstruction -> canonical mesh -> self-contained GLB -> bounded in-memory asset cache -> Three.js viewer/export. The age and research pipelines are separate capability-gated paths; offline research output does not enable production features.

## Build, test, and lint commands

Run commands from the indicated directory in PowerShell.

### Backend

The backend uses the locked `uv` environment and Python 3.11:

```powershell
Set-Location backend
uv --cache-dir ..\output\uv-cache sync --locked --python 3.11
.\.venv\Scripts\python.exe -m agemorph3d
```

Run the backend suite and checks:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check src tests
.\.venv\Scripts\ruff.exe format --check src tests
```

Run one test file or one test node:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_api.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_api.py::test_health -q
```

Tests use synthetic fixtures and adapters. They do not establish real model accuracy, licensing, or G1/G2/G3 acceptance.

### Frontend

The frontend requires Node.js 22.18+ and npm:

```powershell
Set-Location frontend
npm ci
npm run dev
npm run build
npm run typecheck
npm test
npm run test:e2e
```

Run focused tests:

```powershell
npm test -- tests\age.test.ts
npm test -- --test-name-pattern="pattern" tests\age.test.ts
npx playwright test tests\studio.spec.ts --project=Chrome
npx playwright test tests\studio.spec.ts --project=msedge
```

Playwright uses installed Chrome and Edge channels, one worker, and a loopback Vite server. Set `AGEMORPH_E2E_PRODUCTION=1` to exercise the production preview on port 4173 instead of the development server on port 5173.

### Local integrated run

From the repository root, prefer the unified launcher for local service checks:

```powershell
.\tools\local-run.ps1 check
.\tools\local-run.ps1 start
.\tools\local-run.ps1 status
.\tools\local-run.ps1 stop
.\tools\local-run.ps1 start --production
```

Development serves the frontend on `127.0.0.1:5173` and the API on `127.0.0.1:8000`; production builds `frontend/dist` and serves it on `127.0.0.1:4173`. Use the model diagnostic and probe commands documented in `backend/README.md` for explicit offline research checks; do not treat them as production readiness.

## Cross-cutting conventions

- Preserve strict capability gates. `missing`, `loading`, `error`, and `ready` are distinct states; model files existing on disk, a successful synthetic test, or a research report must not be used to infer production readiness.
- Keep static, realtime, age, and research contracts separate. A static GLB does not imply age morph targets; `/api/aging` remains disabled until its explicit qualification conditions are met.
- Preserve unknowns and failures. Do not fill unknown source age, invent observations, collapse no-face/multi-face/occluded cases, or replace a target’s own projection with a source projection.
- Production assets are bounded in memory with TTL/LRU and read leases. Cancellation, timeout, disconnect, and shutdown must prevent late publication and must release the actual work slot only after the underlying task finishes.
- Network-facing behavior is loopback-only. Preserve explicit HTTP/WS origin and host validation, request/frame size limits, timeout budgets, sanitized stable error codes, and the single active worker/no-queue behavior.
- Keep provenance and reproducibility explicit in offline work: preserve source roles, exact hashes/pins, failure denominators, output manifests, and non-overwriting output directories. A report or arithmetic replay is not a model rerun or quality sign-off.
- Keep offline research tools isolated from the FastAPI runtime and model lifecycle. New research pages/harnesses should manage their own loopback server and browser lifecycle and clean up in `finally`.
- Resolve relative manifests and research inputs from the repository root when commands are documented from root; do not accidentally reinterpret them relative to `backend/`.
- Use existing schemas, validators, lifecycle helpers, caches, and contract test patterns before adding parallel logic. Update the relevant contract/protocol documentation when behavior changes.
- Do not modify `.gitignore`, stage ignored artifacts, publish model/data assets, or commit credentials, environments, logs, generated output, or local assistant/session state. Avoid destructive Git operations.

## Documentation and change boundaries

Before implementing a cross-cutting change, check `RULES.md` and the applicable sections of `ARCHITECTURE.md`, `README.md`, and the subsystem’s development record. Treat `PROGRESS.md` and research reports as status/evidence, not as permission to enable unfinished behavior. Keep production code, declarations, execution evidence, real-model results, and quality sign-off distinct.

When changing a protocol or API, update the corresponding schema/contract tests and documentation. When changing a resource or concurrency boundary, cover cancellation, timeout, disconnect, shutdown, and late-result behavior. When changing frontend service behavior, preserve generation/epoch guards so stale asynchronous responses cannot overwrite current UI state.
