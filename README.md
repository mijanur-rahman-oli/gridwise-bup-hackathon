# GridWise — LLM-Assisted Smart Campus Energy Optimization

BUP CSE Fest 2026 · Online Preliminary Round submission.

| | |
|---|---|
| **Team** | Team Webtrix |
| **Public endpoint** | https://gridwise-bup-hackathon.onrender.com |
| **Repository** | https://github.com/mijanur-rahman-oli/gridwise-bup-hackathon |
| **Docker image** | docker.io/mijanurrahmanoli/gridwise:1.0.0 |
| **LLM model** | Groq · llama-3.3-70b-versatile |

---

## 1. What it does

One FastAPI service with two judge-facing endpoints plus a live dashboard:

| Method | Path                | Purpose |
|--------|---------------------|---------|
| GET    | `/health`           | Readiness probe → `{"status":"ok"}` |
| POST   | `/optimize-energy`  | Accepts a 24-hour scenario + 1–3 operator notes. Returns a machine-checkable LLM interpretation **and** a valid, cost-optimal 24-hour schedule. |
| GET    | `/`                 | Live React dashboard (for demo/video) |

### Architecture
operator_notes ─▶ LLM (Groq/OpenAI/Gemini) ─▶ deterministic guardrails
─▶ PuLP MILP optimizer ─▶ self-replay validator ─▶ JSON

text

The LLM is the **only** component that converts free-text notes into structured directives — satisfying the mandatory challenge requirement. Every LLM response is treated as untrusted and re-validated deterministically before entering the optimizer.

---

## 2. Quickstart (local)

```bash
git clone https://github.com/mijanur-rahman-oli/gridwise-bup-hackathon.git
cd gridwise-bup-hackathon

# Configure environment (copy template, then set your API key)
cp .env.example .env
# Edit .env → set LLM_API_KEY. Do NOT commit .env.

# Create virtual environment
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the service
uvicorn app.main:app --host 0.0.0.0 --port 8000


