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
With your existing private `.env` configured on the backend:
```bash
.venv/bin/python implementation/scripts/start_local.py --env-file .env --port 8000
```
Source reload is enabled by default; `--no-reload` explicitly disables it. Keep the same database configuration when restarting. Do not switch databases to hide unavailable sessions.

For a credential-free, isolated preview instead (no genuine provider speech):
```bash
.venv/bin/python implementation/scripts/start_local.py --preview --port 8000
```
API documentation: `http://127.0.0.1:8000/docs`.

### 3. Frontend Setup
In another terminal, from the repository root:
```bash
npm --prefix implementation/frontend ci
```
```bash
npm --prefix implementation/frontend run dev
```
Application: `http://localhost:5173`. Both development and built-app preview proxy `/api` to the same backend; use server-side `VCC_PREVIEW_API_TARGET` when selecting a non-default local backend.

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
