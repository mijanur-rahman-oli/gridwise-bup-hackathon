# GridWise — LLM-Assisted Smart Campus Energy Optimization

BUP CSE Fest 2026 · Online Preliminary Round submission.

| | |
|---|---|
| **Team** | mijanur-rahman-oli |
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
