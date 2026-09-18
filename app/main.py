"""GridWise — LLM-Assisted Smart Campus Energy Optimization Service."""
from __future__ import annotations

import logging
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .schemas import OptimizeRequest, OptimizeResponse
from .llm_interpreter import interpret_notes
from .guardrails import apply_guardrails
from .optimizer import optimize
from .validator import replay


logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
log = logging.getLogger("gridwise")


APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent
STATIC_DIR = ROOT_DIR / "static"

SAMPLES_FILENAME = "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"
SAMPLES_SRC = ROOT_DIR / SAMPLES_FILENAME
SAMPLES_DST = STATIC_DIR / SAMPLES_FILENAME


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(
        "GridWise starting | provider=%s model=%s key=%s static=%s",
        settings.LLM_PROVIDER,
        settings.LLM_MODEL,
        "set" if settings.has_llm() else "MISSING",
        "present" if STATIC_DIR.is_dir() else "missing",
    )
    _prepare_static_assets()
    yield
    log.info("GridWise shutting down")


def _prepare_static_assets() -> None:
    if not STATIC_DIR.is_dir():
        log.warning("static/ directory not found at %s", STATIC_DIR)
        return
    if not SAMPLES_SRC.is_file():
        log.warning("Sample-cases file not found at %s", SAMPLES_SRC)
        return
    try:
        needs_copy = (
            not SAMPLES_DST.is_file()
            or SAMPLES_SRC.stat().st_mtime > SAMPLES_DST.stat().st_mtime
        )
        if needs_copy:
            shutil.copyfile(SAMPLES_SRC, SAMPLES_DST)
            log.info("Copied %s → static/", SAMPLES_FILENAME)
    except Exception as e:  # noqa: BLE001
        log.warning("Could not sync %s: %s", SAMPLES_FILENAME, e)


app = FastAPI(
    title="GridWise",
    version="1.1.0",
    description="LLM-Assisted Smart Campus Energy Optimization (BUP CSE Fest 2026)",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def index():
    index_file = STATIC_DIR / "index.html"
    if index_file.is_file():
        return FileResponse(str(index_file))
    return JSONResponse(
        {
            "service": "GridWise",
            "version": app.version,
            "endpoints": {
                "health": "GET /health",
                "optimize": "POST /optimize-energy",
                "docs": "GET /docs",
            },
            "note": "UI not bundled; API is fully operational.",
        }
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/optimize-energy", response_model=OptimizeResponse)
async def optimize_energy(req: OptimizeRequest, request: Request) -> OptimizeResponse:
    t0 = time.perf_counter()

    battery_dict = req.battery.model_dump()
    try:
        raw_interps = await interpret_notes(req.operator_notes, battery_dict)
        log.info(
            "[%s] LLM produced %d raw interpretation(s)",
            req.scenario_id, len(raw_interps),
        )
    except Exception as e:  # noqa: BLE001
        log.exception("[%s] LLM layer raised unexpectedly: %s", req.scenario_id, e)
        raw_interps = [
            {
                "note_index": i,
                "applies": False,
                "directive_type": "no_op",
                "structured_adjustment": None,
                "explanation": "Interpretation unavailable.",
            }
            for i in range(len(req.operator_notes))
        ]

    clean_interps, constraints = apply_guardrails(raw_interps, battery_dict)
    applied = sum(1 for x in clean_interps if x["applies"])
    log.info(
        "[%s] guardrails accepted %d/%d note(s)",
        req.scenario_id, applied, len(clean_interps),
    )

    hours_dict = [h.model_dump() for h in req.hours]
    try:
        result = optimize(hours_dict, battery_dict, constraints)
    except Exception as e:  # noqa: BLE001
        log.exception("[%s] solver failure: %s", req.scenario_id, e)
        raise HTTPException(status_code=500, detail="Optimization failed.")

    errors = replay(result["plan"], hours_dict, battery_dict, constraints)
    if errors:
        log.error(
            "[%s] self-replay found %d violation(s): %s",
            req.scenario_id, len(errors), errors[:5],
        )
        safe_constraints = {
            "solar_factor": [1.0] * 24,
            "min_energy": [float(battery_dict["minimum_energy_kwh"])] * 24,
            "no_charge": [False] * 24,
            "no_discharge": [False] * 24,
            "grid_cap": [None] * 24,
        }
        try:
            result = optimize(hours_dict, battery_dict, safe_constraints)
            errors2 = replay(result["plan"], hours_dict, battery_dict, safe_constraints)
            if errors2:
                log.error(
                    "[%s] fallback also failed replay: %s",
                    req.scenario_id, errors2[:3],
                )
                raise HTTPException(status_code=500, detail="Optimization failed.")
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("[%s] fallback solve failed: %s", req.scenario_id, e)
            raise HTTPException(status_code=500, detail="Optimization failed.")

    dt = time.perf_counter() - t0
    log.info(
        "[%s] solved in %.2fs | cost=%.2f grid=%.1f peak=%.1f",
        req.scenario_id, dt,
        result["total_cost_bdt"],
        result["total_grid_kwh"],
        result["peak_grid_kwh"],
    )

    n_notes = len(clean_interps)
    summary = (
        f"Applied {applied} of {n_notes} operator note(s). "
        f"Grid import {result['total_grid_kwh']:.1f} kWh "
        f"at BDT {result['total_cost_bdt']:.2f}; "
        f"peak {result['peak_grid_kwh']:.1f} kWh. "
        f"Solved in {dt:.2f}s."
    )

    return OptimizeResponse(
        scenario_id=req.scenario_id,
        directive_interpretation=clean_interps,
        hourly_plan=result["plan"],
        total_grid_kwh=result["total_grid_kwh"],
        total_cost_bdt=result["total_cost_bdt"],
        peak_grid_kwh=result["peak_grid_kwh"],
        plan_summary=summary,
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal error."})