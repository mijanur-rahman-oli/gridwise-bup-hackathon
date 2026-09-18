"""Runs all 10 public sample cases against the service in-process."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

SAMPLES_FILENAME = "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"
SAMPLES_PATH = Path(__file__).resolve().parent.parent / SAMPLES_FILENAME

SAMPLES = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))
client = TestClient(app)
TOL = 0.01


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.parametrize(
    "case", SAMPLES["cases"], ids=[c["id"] for c in SAMPLES["cases"]]
)
def test_sample_case(case):
    payload = case["input"]
    r = client.post("/optimize-energy", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["scenario_id"] == payload["scenario_id"]
    assert len(body["directive_interpretation"]) == len(payload["operator_notes"])
    assert len(body["hourly_plan"]) == 24

    idxs = [d["note_index"] for d in body["directive_interpretation"]]
    assert idxs == list(range(len(payload["operator_notes"])))

    total_grid = sum(h["grid_kwh"] for h in body["hourly_plan"])
    assert abs(total_grid - body["total_grid_kwh"]) < TOL

    peak = max(h["grid_kwh"] for h in body["hourly_plan"])
    assert abs(peak - body["peak_grid_kwh"]) < TOL

    initial = payload["battery"]["initial_energy_kwh"]
    final = body["hourly_plan"][-1]["battery_energy_after_kwh"]
    assert abs(final - initial) < TOL