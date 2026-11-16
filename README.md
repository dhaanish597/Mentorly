# Mentorly

> **Mentorly** is a voice-first technical interview coaching and computer science learning platform. It combines structured lessons, workspace-owned progress, source-grounded repository learning, and configurable Gnani speech. Live arbitrary-code execution and full native-language localization are not yet release-verified.

---

The current deployment is not yet accepted: PostgreSQL integration and public sandbox acceptance are incomplete. See [deployment status](DEPLOYMENT_STATUS.md). The engineering recovery and all 40 original requirements are tracked in [final build status](docs/engineering/FINAL_BUILD_STATUS.md).

## 🌟 Key Features

- **🎙️ Voice-First Coaching & Socratic Dialogue**: Interactive voice-based interviews with real-time speech synthesis (TTS) and speech-to-text (STT), supporting English, Tanglish, and regional speech models.
- **💻 Integrated Monaco Code Studio**: Real-time code editing, syntax analysis, AST keyterm validation, and fail-closed isolated code execution.
- **📚 Dynamic Curriculum & Learning Modules**: Curated tracks covering Data Structures & Algorithms, System Design, Core CS Concepts, and General Technical Aptitude.
- **🔄 Repository Learning & Redrive Engine**: Ingest real GitHub repositories, auto-generate contextual interview questions, and redrive learning sessions based on learner history.
- **🏆 Evidence-Based Progress**: Workspace-owned lesson and interview activity, prerequisite-aware recommendations, earned milestone badges, and reopenable interview reports. Legacy fake-personalization endpoints are retired; there is no live leaderboard.

---

## 📂 Repository Architecture

```text
.
├── implementation/       # Production source code
│   ├── backend/          # FastAPI REST & WebSocket APIs, SQLite persistence,
│   │                     # Socratic coach engine, Gnani speech adapters, and test suites
│   ├── frontend/         # React 18 + TypeScript frontend with Monaco Editor,
│   │                     # Web Audio streamer, and interactive learning components
│   └── scripts/          # Secret checkers, schema drift monitors, and smoke test harnesses
├── horizon/              # Next.js interactive web interface & design system
├── docs/                 # Engineering specifications, architecture audit, & implementation plans
│   ├── engineering/      # Full product audits and implementation trackers
│   └── *.md              # Strategic blueprints, challenge briefs, and architectural roadmaps
├── recordings/           # Video and audio interaction proofs, test scripts, and UI captures
└── tooling/              # Development utilities, import tools, and deployment tunnels
```

---

## 🚀 Quick Start

### 1. Prerequisites
- **Python**: 3.11+
- **Node.js**: 20+ (with `npm` or `pnpm`)

### 2. Backend Setup
Run from the repository root, using the existing project virtual environment where available. For a fresh checkout:
```bash
python3 -m venv .venv
```
```bash
.venv/bin/python -m pip install -r implementation/backend/requirements.txt
```
With an explicitly selected private server environment file (absolute path, owned by you and not writable by other users):
```bash
.venv/bin/python implementation/scripts/start_local.py --env-file /absolute/private/server.env
```
Source reload is enabled by default; `--no-reload` explicitly disables it. Keep the same database configuration when restarting. Do not switch databases to hide unavailable sessions.

For a credential-free, isolated preview instead (no genuine provider speech):
```bash
.venv/bin/python implementation/scripts/start_local.py --preview
```
API documentation: `http://127.0.0.1:8020/docs`. Startup never invokes providers. `VCC_ENV_FILE` is an explicit alternative to `--env-file`; ambient `.env` discovery stays disabled.

### 3. Frontend Setup
In another terminal, from the repository root:
```bash
npm --prefix implementation/frontend ci
```
```bash
npm --prefix implementation/frontend run dev
```
Application: `http://localhost:5173`. Both development and built-app preview proxy `/api` to the same backend; use server-side `VCC_PREVIEW_API_TARGET` when selecting a non-default local backend.

Defaults come from `implementation/config/local-development.json`: backend8020, frontend5173, CORS for both loopback hostnames. For another session, choose free ports and pass the same `VCC_BACKEND_PORT` / `VCC_FRONTEND_PORT` to Vite and `--port` / `--frontend-port` to the launcher. Explicit legacy targets remain supported. A production static build requires a same-origin HTTPS reverse proxy forwarding `/api/v1` (including streaming/WS) to the coordinator; the Vite dev proxy does not route a deployed build.

Credential-safe diagnostics:
```bash
.venv/bin/python implementation/scripts/doctor.py
```
Use `--env-file /absolute/private/server.env` for configured development or `--offline` to skip the local health request. Diagnostics show readiness and addresses, never credential values. Settings → Privacy contains opt-in workspace recovery, credential revocation, record export and local draft backup/import. Recovery preserves server records and keeps bearer capabilities tab-scoped; record retention and session expiry still apply.

This isolated audit repair is tracked in [remediation plan](docs/engineering/SECTIONS_2_3_4_REMEDIATION_PLAN.md) and [measured status](docs/engineering/SECTIONS_2_3_4_REMEDIATION_STATUS.md). Review its task-specific delta before integrating with concurrent deployment work.

Diagnose repeated **Not Found / Retry** without provider calls:
```bash
.venv/bin/python implementation/scripts/check_local_api.py --base-url http://127.0.0.1:5173
```
A health check alone does not prove the newer curriculum/interview APIs are loaded. Restart an outdated backend rather than repeatedly retrying missing routes. In this working folder, `.venv-takeover/bin/python` is the existing tested interpreter.

### 4. Running Horizon Web App
```bash
# Navigate to horizon
cd horizon

# Install dependencies
pnpm install

# Start Next.js development server
pnpm dev
```

---

## 🧪 Verification & Quality Checks

Run the verification suite from the repository root:

```bash
# Secret hygiene check
python3 implementation/scripts/check_secrets.py

# Schema drift validation
PYTHONPATH=implementation/backend:implementation python3 implementation/scripts/check_schema_drift.py --check --self-test

# Complete test suite
pytest implementation/backend/tests
```

---

## 🔒 Security & Privacy

- All environment variables and API keys are strictly guarded via `.gitignore` and validation scripts (`check_secrets.py`).
- Isolated execution uses fail-closed sandbox policies to safely evaluate learner code.
