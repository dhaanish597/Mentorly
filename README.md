# Mentorly

> **Mentorly** is an intelligent, voice-first technical interview coaching and computer science learning platform. Powered by AI-driven Socratic tutoring, multimodal speech (English & Tanglish), real-time code execution, and comprehensive curriculum tracking.

---

## 🌟 Key Features

- **🎙️ Voice-First Coaching & Socratic Dialogue**: Interactive voice-based interviews with real-time speech synthesis (TTS) and speech-to-text (STT), supporting English, Tanglish, and regional speech models.
- **💻 Integrated Monaco Code Studio**: Real-time code editing, syntax analysis, AST keyterm validation, and fail-closed isolated code execution.
- **📚 Dynamic Curriculum & Learning Modules**: Curated tracks covering Data Structures & Algorithms, System Design, Core CS Concepts, and General Technical Aptitude.
- **🔄 Repository Learning & Redrive Engine**: Ingest real GitHub repositories, auto-generate contextual interview questions, and redrive learning sessions based on learner history.
- **🏆 Gamification & Progress Tracking**: Daily goals, streak accounting, XP, live leaderboards, and detailed performance metrics.

---

## 📂 Repository Architecture

```text
.
├── implementation/       # Production source code
│   ├── backend/          # FastAPI REST & WebSocket APIs, SQLite/PostgreSQL DB migrations,
│   │                     # Socratic coach engine, Gnani speech adapters, and test suites
│   ├── frontend/         # React 19 + TypeScript frontend with Monaco Editor,
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
```bash
# Navigate to implementation directory
cd implementation

# Install dependencies (or activate your virtual environment)
pip install -r backend/requirements.txt  # or use existing .venv

# Run FastAPI backend server
python -m uvicorn backend.app.main:app --app-dir . --host 127.0.0.1 --port 8000 --reload
```
API Documentation will be available at: `http://127.0.0.1:8000/docs`

### 3. Frontend Setup
```bash
# Navigate to frontend
cd implementation/frontend

# Install dependencies
npm install

# Start Vite development server
npm run dev
```
Access the application at: `http://127.0.0.1:5173`

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
