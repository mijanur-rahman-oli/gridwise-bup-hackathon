"""MILP energy optimizer built with PuLP + CBC."""
import logging
from typing import Any, Dict, List

import pulp

log = logging.getLogger("gridwise.optimizer")

HOURS = list(range(24))
TOL = 1e-6


def optimize(
    hours: List[Dict[str, Any]],
    battery: Dict[str, Any],
    constraints: Dict[str, Any],
) -> Dict[str, Any]:
    demand = {h["hour"]: float(h["demand_kwh"]) for h in hours}
    solar = {h["hour"]: float(h["solar_kwh"]) for h in hours}
    tariff = {h["hour"]: float(h["tariff_bdt_per_kwh"]) for h in hours}

    cap = float(battery["capacity_kwh"])
    e0 = float(battery["initial_energy_kwh"])
    min_e = constraints["min_energy"]
    charge_max = float(battery["max_charge_kwh_per_hour"])
    dis_max = float(battery["max_discharge_kwh_per_hour"])
    eff_solar = {h: solar[h] * constraints["solar_factor"][h] for h in HOURS}
    no_charge = constraints["no_charge"]
    no_dis = constraints["no_discharge"]
    grid_cap = constraints["grid_cap"]

    prob = pulp.LpProblem("gridwise", pulp.LpMinimize)

    grid = pulp.LpVariable.dicts("grid", HOURS, lowBound=0, cat="Continuous")
    su = pulp.LpVariable.dicts("su", HOURS, lowBound=0, cat="Continuous")
    ch = pulp.LpVariable.dicts("ch", HOURS, lowBound=0, cat="Continuous")
    dis = pulp.LpVariable.dicts("dis", HOURS, lowBound=0, cat="Continuous")
    soc = pulp.LpVariable.dicts("soc", HOURS, lowBound=0, upBound=cap, cat="Continuous")
    y_ch = pulp.LpVariable.dicts("ych", HOURS, cat="Binary")
    y_dis = pulp.LpVariable.dicts("ydis", HOURS, cat="Binary")

    prob += pulp.lpSum(grid[h] * tariff[h] for h in HOURS)

    for h in HOURS:
        prob += su[h] <= eff_solar[h]
        prob += ch[h] <= charge_max * y_ch[h]
        prob += dis[h] <= dis_max * y_dis[h]
        prob += y_ch[h] + y_dis[h] <= 1
        if no_charge[h]:
            prob += ch[h] == 0
        if no_dis[h]:
            prob += dis[h] == 0
        if grid_cap[h] is not None:
            prob += grid[h] <= grid_cap[h]

        prob += grid[h] + su[h] + dis[h] == demand[h] + ch[h]

        if h == 0:
            prob += soc[h] == e0 + ch[h] - dis[h]
        else:
            prob += soc[h] == soc[h - 1] + ch[h] - dis[h]

        prob += soc[h] >= min_e[h]

    prob += soc[23] == e0

    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=20)
    status = prob.solve(solver)
    if pulp.LpStatus[status] != "Optimal":
        log.error("MILP status: %s", pulp.LpStatus[status])
        raise RuntimeError(f"Optimization failed: {pulp.LpStatus[status]}")

    plan = []
    for h in HOURS:
        g = max(0.0, float(pulp.value(grid[h]) or 0.0))
        s = max(0.0, float(pulp.value(su[h]) or 0.0))
        c = max(0.0, float(pulp.value(ch[h]) or 0.0))
        d = max(0.0, float(pulp.value(dis[h]) or 0.0))

        if c < 1e-6:
            c = 0.0
        if d < 1e-6:
            d = 0.0

        if c > TOL and c >= d:
            action, mag = "charge", c
            d = 0.0
        elif d > TOL and d > c:
            action, mag = "discharge", d
            c = 0.0
        else:
            action, mag = "idle", 0.0
            c = d = 0.0

        if h == 0:
            e = e0 + c - d
        else:
            e = plan[-1]["battery_energy_after_kwh"] + c - d

        plan.append(
            {
                "hour": h,
                "grid_kwh": round(g, 4),
                "solar_used_kwh": round(s, 4),
                "battery_action": action,
                "battery_kwh": round(mag, 4),
                "battery_energy_after_kwh": round(e, 4),
            }
        )

    total_grid = sum(p["grid_kwh"] for p in plan)
    total_cost = sum(p["grid_kwh"] * tariff[p["hour"]] for p in plan)
    peak_grid = max(p["grid_kwh"] for p in plan)

    return {
        "plan": plan,
        "total_grid_kwh": round(total_grid, 4),
        "total_cost_bdt": round(total_cost, 4),
        "peak_grid_kwh": round(peak_grid, 4),
    }