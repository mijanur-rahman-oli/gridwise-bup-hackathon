"""Independent replay of the returned hourly_plan against all rules."""
from typing import Any, Dict, List

TOL = 0.01


def replay(
    plan: List[Dict[str, Any]],
    hours: List[Dict[str, Any]],
    battery: Dict[str, Any],
    constraints: Dict[str, Any],
) -> List[str]:
    errors: List[str] = []
    by_h = {h["hour"]: h for h in hours}
    cap = float(battery["capacity_kwh"])
    e0 = float(battery["initial_energy_kwh"])
    charge_max = float(battery["max_charge_kwh_per_hour"])
    dis_max = float(battery["max_discharge_kwh_per_hour"])
    min_e = constraints["min_energy"]
    no_charge = constraints["no_charge"]
    no_dis = constraints["no_discharge"]
    grid_cap = constraints["grid_cap"]
    solar_factor = constraints["solar_factor"]

    prev_e = e0
    for p in plan:
        h = p["hour"]
        src = by_h[h]
        eff_solar = float(src["solar_kwh"]) * solar_factor[h]

        if p["solar_used_kwh"] > eff_solar + TOL:
            errors.append(f"h{h}: solar_used {p['solar_used_kwh']} > eff {eff_solar}")

        if p["battery_action"] == "idle" and p["battery_kwh"] > TOL:
            errors.append(f"h{h}: idle with battery_kwh>0")
        if p["battery_action"] == "charge" and p["battery_kwh"] > charge_max + TOL:
            errors.append(f"h{h}: charge rate exceeded")
        if p["battery_action"] == "discharge" and p["battery_kwh"] > dis_max + TOL:
            errors.append(f"h{h}: discharge rate exceeded")
        if no_charge[h] and p["battery_action"] == "charge":
            errors.append(f"h{h}: charged during no_charge_window")
        if no_dis[h] and p["battery_action"] == "discharge":
            errors.append(f"h{h}: discharged during no_discharge_window")
        if grid_cap[h] is not None and p["grid_kwh"] > grid_cap[h] + TOL:
            errors.append(f"h{h}: grid {p['grid_kwh']} > cap {grid_cap[h]}")

        lhs = p["grid_kwh"] + p["solar_used_kwh"] + (
            p["battery_kwh"] if p["battery_action"] == "discharge" else 0.0
        )
        rhs = float(src["demand_kwh"]) + (
            p["battery_kwh"] if p["battery_action"] == "charge" else 0.0
        )
        if abs(lhs - rhs) > TOL:
            errors.append(f"h{h}: energy balance {lhs} != {rhs}")

        expected = prev_e + (
            p["battery_kwh"] if p["battery_action"] == "charge"
            else -p["battery_kwh"] if p["battery_action"] == "discharge"
            else 0.0
        )
        if abs(expected - p["battery_energy_after_kwh"]) > TOL:
            errors.append(
                f"h{h}: soc mismatch {expected} vs {p['battery_energy_after_kwh']}"
            )
        if p["battery_energy_after_kwh"] > cap + TOL:
            errors.append(f"h{h}: soc > capacity")
        if p["battery_energy_after_kwh"] < min_e[h] - TOL:
            errors.append(
                f"h{h}: soc {p['battery_energy_after_kwh']} < min {min_e[h]}"
            )

        prev_e = p["battery_energy_after_kwh"]

    if abs(prev_e - e0) > TOL:
        errors.append(f"End-of-day soc {prev_e} != initial {e0}")
    return errors