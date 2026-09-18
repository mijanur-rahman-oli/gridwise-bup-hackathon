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

```
operator_notes ─▶ LLM (Groq/OpenAI/Gemini) ─▶ deterministic guardrails
              ─▶ PuLP MILP optimizer ─▶ self-replay validator ─▶ JSON
```

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
```

### Verify

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

### Run a public sample

```bash
curl -s -X POST http://localhost:8000/optimize-energy \
  -H "Content-Type: application/json" \
  -d "$(python -c "import json; print(json.dumps(json.load(open('BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json'))['cases'][0]['input']))")" \
  | python -m json.tool | head -40
```

### Run all 10 public samples

```bash
pytest tests/ -v
```

Expected: **11 passed** (1 × `/health` + 10 × sample cases).

### Open the dashboard

```
http://localhost:8000/
```

---

## 3. Docker fallback

```bash
docker pull mijanurrahmanoli/gridwise:1.0.0

docker run --rm -p 8000:8000 \
  -e LLM_PROVIDER=groq \
  -e LLM_API_KEY=$LLM_API_KEY \
  -e LLM_MODEL=llama-3.3-70b-versatile \
  -e LLM_BASE_URL=https://api.groq.com/openai/v1 \
  mijanurrahmanoli/gridwise:1.0.0

curl http://localhost:8000/health
# {"status":"ok"}
```

The image:

- Exposes port **8000**
- Binds to **0.0.0.0**
- Contains **no baked-in secrets**
- Has a built-in healthcheck against `/health`

---

## 4. Environment variables

| Name                   | Required | Purpose |
|------------------------|----------|---------|
| `LLM_PROVIDER`         | yes      | `groq` \| `openai` \| `gemini` |
| `LLM_API_KEY`          | yes      | Provider API key — **never commit** |
| `LLM_MODEL`            | yes      | e.g. `llama-3.3-70b-versatile` |
| `LLM_BASE_URL`         | yes      | OpenAI-compatible base URL |
| `LLM_TIMEOUT_SECONDS`  | no       | default 15 |
| `REQUEST_TIMEOUT_SECONDS` | no    | default 25 |
| `PORT`                 | no       | default 8000 |
| `LOG_LEVEL`            | no       | default INFO |

---

## 5. LLM role & guardrails

### LLM role

The LLM converts each `operator_notes[i]` into **exactly one** structured directive (or marks it `no_op`). Its output is the source of the constraints the optimizer enforces. The mandatory-challenge requirement is satisfied because the LLM is the only component that reads natural language.

### Deterministic guardrails (`app/guardrails.py`)

Every LLM response is treated as untrusted. These rules are enforced before the optimizer runs:

- Directive type ∈ {`solar_reduction`, `minimum_battery_reserve`, `no_charge_window`, `no_discharge_window`, `max_grid_window`, `no_op`}
- `hours` unique integers in `[0, 23]`, returned in ascending order
- `factor ∈ [0, 1]`, `minimum_energy_kwh ≤ capacity_kwh`, `max_grid_kwh ≥ 0`
- `applies=true` for every non-`no_op` directive; `applies=false` + `structured_adjustment=null` **only** for `no_op`
- Exactly one entry per note, in `note_index` order
- Any invalid entry degrades **that specific note** to `no_op` — the service never crashes and never invents a directive

---

## 6. Optimizer

- **Solver:** PuLP with CBC (bundled MILP solver)
- **Decision variables per hour:** `grid[h]`, `solar_used[h]`, `charge[h]`, `discharge[h]`, `soc[h]`, binary `y_ch[h]`, `y_dis[h]`
- **Objective:** `min Σ grid[h] · tariff[h]`
- **Hard constraints:**
  - Hourly energy balance: `grid + solar_used + discharge = demand + charge`
  - Battery bounds: `min_energy ≤ soc ≤ capacity`
  - Hourly rate limits: `charge ≤ max_charge`, `discharge ≤ max_discharge`
  - Cannot charge and discharge in the same hour
  - `soc[23] = soc_init` (end-of-day neutrality)
  - Every applicable directive (solar factor, reserve floor, no-charge/no-discharge windows, grid caps)

### Self-replay validator (`app/validator.py`)

After solving, an independent replay walks the returned plan hour-by-hour to re-verify directive compliance, energy balance, battery transitions, and totals consistency. If the replay detects any violation, the optimizer retries with conservative constraints so the service still returns a valid plan.

---

## 7. Public Sample Cases

The file `BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json` is the organizer-provided sample pack. **Its contents are not modified.**

- Loaded by the test suite (`pytest tests/ -v`)
- Auto-copied into `static/` at server startup so the dashboard dropdown can fetch it
- Served at `/static/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json`

---

## 8. Project structure

```
gridwise-bup-hackathon/
├── app/
│   ├── __init__.py
│   ├── config.py               # env vars
│   ├── schemas.py              # Pydantic request/response models
│   ├── llm_interpreter.py      # LLM → structured directives
│   ├── guardrails.py           # deterministic validation
│   ├── optimizer.py            # PuLP MILP + CBC
│   ├── validator.py            # post-solve replay
│   └── main.py                 # FastAPI app
├── static/
│   └── index.html              # Live React dashboard
├── tests/
│   └── test_public_samples.py  # 11 tests
├── BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── render.yaml
├── .env.example
├── .gitignore
├── .dockerignore
└── README.md
```

---

## 9. Known limitations

- CBC may take longer on pathological numeric conditioning; typical scenarios solve in under 1 second.
- If the LLM provider is unreachable, affected notes safely degrade to `no_op` and the optimizer still returns a valid plan. The service never returns a 5xx due to LLM failure.
- Secret values are never logged; stack traces are sanitised in HTTP responses.
- The dashboard uses CDN-loaded Tailwind/Babel/Chart.js — harmless warnings in the browser console; the judge harness only uses the JSON API.

---

## 10. Dependencies (credited)

| Library | Purpose |
|---|---|
| **FastAPI** | HTTP service |
| **Uvicorn** | ASGI server |
| **Pydantic v2** | Request/response validation |
| **PuLP** (CBC) | MILP optimization |
| **httpx** | Async HTTP client for LLM provider |
| **Tenacity** | Retry logic on LLM calls |
| **python-dotenv** | `.env` loading |
| **pytest** | Test suite |

Default LLM provider: **Groq · llama-3.3-70b-versatile** (configurable via env vars).

---

## 11. Submission links

| Item | URL |
|---|---|
| Public endpoint | https://gridwise-bup-hackathon.onrender.com |
| Health probe | https://gridwise-bup-hackathon.onrender.com/health |
| Repository | https://github.com/mijanur-rahman-oli/gridwise-bup-hackathon |
| Docker Hub | https://hub.docker.com/r/mijanurrahmanoli/gridwise |
| Docker pull | `docker pull mijanurrahmanoli/gridwise:1.0.0` |