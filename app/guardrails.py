"""Deterministic guardrails applied to raw LLM output."""
import logging
from typing import Any, Dict, List, Tuple

log = logging.getLogger("gridwise.guardrails")

ALLOWED = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
}


def _valid_hours(hours: Any) -> bool:
    if not isinstance(hours, list) or not hours:
        return False
    if not all(isinstance(h, int) and 0 <= h <= 23 for h in hours):
        return False
    if len(set(hours)) != len(hours):
        return False
    if hours != sorted(hours):
        return False
    return True


def _finite_nonneg(x: Any) -> bool:
    return (
        isinstance(x, (int, float))
        and x == x
        and x >= 0
        and x != float("inf")
        and x != float("-inf")
    )


def validate_interpretation(
    raw: Dict[str, Any],
    note_index: int,
    battery: Dict[str, Any],
) -> Dict[str, Any]:
    safe = {
        "note_index": note_index,
        "applies": False,
        "directive_type": "no_op",
        "structured_adjustment": None,
        "explanation": "Guardrails rejected the interpretation; treated as no_op.",
    }
    try:
        dtype = raw.get("directive_type")
        if dtype not in ALLOWED:
            return safe

        adj = raw.get("structured_adjustment")
        expl = str(raw.get("explanation", ""))[:400]

        if dtype == "no_op":
            return {
                "note_index": note_index,
                "applies": False,
                "directive_type": "no_op",
                "structured_adjustment": None,
                "explanation": expl or "Note does not affect the 24-hour schedule.",
            }

        if not isinstance(adj, dict):
            return safe
        hours = adj.get("hours")
        if not _valid_hours(hours):
            return safe

        if dtype == "solar_reduction":
            f = adj.get("factor")
            if not isinstance(f, (int, float)) or not (0.0 <= float(f) <= 1.0):
                return safe
            adj_clean = {"hours": list(hours), "factor": float(f)}

        elif dtype == "minimum_battery_reserve":
            k = adj.get("minimum_energy_kwh")
            cap = float(battery["capacity_kwh"])
            if not _finite_nonneg(k) or float(k) > cap + 1e-9:
                return safe
            adj_clean = {"hours": list(hours), "minimum_energy_kwh": float(k)}

        elif dtype == "no_charge_window":
            adj_clean = {"hours": list(hours)}

        elif dtype == "no_discharge_window":
            adj_clean = {"hours": list(hours)}

        elif dtype == "max_grid_window":
            k = adj.get("max_grid_kwh")
            if not _finite_nonneg(k):
                return safe
            adj_clean = {"hours": list(hours), "max_grid_kwh": float(k)}

        else:
            return safe

        return {
            "note_index": note_index,
            "applies": True,
            "directive_type": dtype,
            "structured_adjustment": adj_clean,
            "explanation": expl or f"Applied {dtype}.",
        }
    except Exception as e:  # noqa: BLE001
        log.warning("guardrail error on note %d: %s", note_index, e)
        return safe


def apply_guardrails(
    raw_interps: List[Dict[str, Any]],
    battery: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    clean_interps: List[Dict[str, Any]] = []
    for i, raw in enumerate(raw_interps):
        clean_interps.append(validate_interpretation(raw, i, battery))

    n = 24
    solar_factor = [1.0] * n
    min_energy = [float(battery["minimum_energy_kwh"])] * n
    no_charge = [False] * n
    no_discharge = [False] * n
    grid_cap: List[Any] = [None] * n

    for interp in clean_interps:
        if not interp["applies"]:
            continue
        adj = interp["structured_adjustment"] or {}
        hours = adj.get("hours", [])
        dtype = interp["directive_type"]

        if dtype == "solar_reduction":
            f = adj["factor"]
            for h in hours:
                solar_factor[h] = min(solar_factor[h], f)
        elif dtype == "minimum_battery_reserve":
            k = adj["minimum_energy_kwh"]
            for h in hours:
                min_energy[h] = max(min_energy[h], k)
        elif dtype == "no_charge_window":
            for h in hours:
                no_charge[h] = True
        elif dtype == "no_discharge_window":
            for h in hours:
                no_discharge[h] = True
        elif dtype == "max_grid_window":
            k = adj["max_grid_kwh"]
            for h in hours:
                grid_cap[h] = k if grid_cap[h] is None else min(grid_cap[h], k)

    constraints = {
        "solar_factor": solar_factor,
        "min_energy": min_energy,
        "no_charge": no_charge,
        "no_discharge": no_discharge,
        "grid_cap": grid_cap,
    }
    return clean_interps, constraints