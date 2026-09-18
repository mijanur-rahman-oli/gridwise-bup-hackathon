"""Pydantic schemas matching the Problem Statement verbatim."""
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

DirectiveType = Literal[
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
]
BatteryAction = Literal["charge", "discharge", "idle"]


# ─── Request ───────────────────────────────────────────────────────
class HourEntry(BaseModel):
    hour: int = Field(..., ge=0, le=23)
    demand_kwh: float = Field(..., ge=0)
    solar_kwh: float = Field(..., ge=0)
    tariff_bdt_per_kwh: float = Field(..., ge=0)


class BatterySpec(BaseModel):
    capacity_kwh: float = Field(..., gt=0)
    initial_energy_kwh: float = Field(..., ge=0)
    minimum_energy_kwh: float = Field(..., ge=0)
    max_charge_kwh_per_hour: float = Field(..., gt=0)
    max_discharge_kwh_per_hour: float = Field(..., gt=0)


class OptimizeRequest(BaseModel):
    scenario_id: str = Field(..., min_length=1)
    operator_notes: List[str] = Field(..., min_length=1, max_length=3)
    hours: List[HourEntry]
    battery: BatterySpec

    @field_validator("operator_notes")
    @classmethod
    def notes_nonempty(cls, v):
        if any(not n.strip() for n in v):
            raise ValueError("operator_notes must not contain empty strings")
        return v

    @model_validator(mode="after")
    def check_hours(self):
        if len(self.hours) != 24:
            raise ValueError("hours must contain exactly 24 entries")
        hs = sorted(h.hour for h in self.hours)
        if hs != list(range(24)):
            raise ValueError("hours must be unique integers 0..23")
        b = self.battery
        if b.initial_energy_kwh > b.capacity_kwh:
            raise ValueError("initial_energy_kwh > capacity_kwh")
        if b.minimum_energy_kwh > b.capacity_kwh:
            raise ValueError("minimum_energy_kwh > capacity_kwh")
        return self


# ─── Response ──────────────────────────────────────────────────────
class StructuredAdjustment(BaseModel):
    hours: Optional[List[int]] = None
    factor: Optional[float] = None
    minimum_energy_kwh: Optional[float] = None
    max_grid_kwh: Optional[float] = None


class DirectiveInterpretation(BaseModel):
    note_index: int
    applies: bool
    directive_type: DirectiveType
    structured_adjustment: Optional[StructuredAdjustment]
    explanation: str


class HourlyPlanEntry(BaseModel):
    hour: int
    grid_kwh: float = Field(..., ge=0)
    solar_used_kwh: float = Field(..., ge=0)
    battery_action: BatteryAction
    battery_kwh: float = Field(..., ge=0)
    battery_energy_after_kwh: float


class OptimizeResponse(BaseModel):
    scenario_id: str
    directive_interpretation: List[DirectiveInterpretation]
    hourly_plan: List[HourlyPlanEntry]
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float
    plan_summary: str