"""LLM-based operator-note interpreter.

The LLM is the *only* component that converts natural language into a
structured directive. Output is treated as untrusted and MUST pass
deterministic guardrails before entering the optimizer.
"""
import json
import logging
import re
from typing import Any, Dict, List

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import settings

log = logging.getLogger("gridwise.llm")


SYSTEM_PROMPT = """You are an energy-scheduling directive extractor for a smart campus.

You will receive operator notes written in natural language and MUST convert each
note into EXACTLY ONE of the following directive types:

1. solar_reduction        — usable solar reduced during hours.
                            structured_adjustment: {"hours": [...], "factor": f}
                            factor = REMAINING usable fraction (0..1).
                            Example: "80% reduction" → factor 0.2.
2. minimum_battery_reserve — minimum stored energy (kWh) required in hours.
                            structured_adjustment: {"hours": [...], "minimum_energy_kwh": k}
                            Relative language (e.g. "50% of capacity") MUST be converted
                            to absolute kWh using the battery.capacity_kwh given.
3. no_charge_window       — charging disabled in hours.
                            structured_adjustment: {"hours": [...]}
4. no_discharge_window    — discharging disabled in hours.
                            structured_adjustment: {"hours": [...]}
5. max_grid_window        — grid import cap (kWh) in hours.
                            structured_adjustment: {"hours": [...], "max_grid_kwh": k}
6. no_op                  — note does NOT affect today's 24-hour schedule.
                            structured_adjustment: null. applies=false.

STRICT RULES:
- Time windows are START-INCLUSIVE, END-EXCLUSIVE and use 24-hour clock.
  "1 PM to 3 PM" → [13, 14].  "6 PM until 9 PM" → [18, 19, 20].
- "hours" must be UNIQUE integers 0..23 in ASCENDING order.
- For solar_reduction, factor is the fraction of solar REMAINING (0 <= factor <= 1).
- For minimum_battery_reserve, express the value in ABSOLUTE kWh, not percentages.
- If a note mentions a relative reserve like "half the battery", compute
  0.5 * battery.capacity_kwh and use that absolute value.
- If a note does not describe any of these operating constraints (e.g. events,
  menus, registrations, unrelated announcements) → directive_type = "no_op",
  applies = false, structured_adjustment = null.
- NEVER invent a directive type outside this list.
- NEVER change demand, tariff, or battery parameters.
- applies = true for every non-no_op directive; applies = false ONLY for no_op.

Respond with ONLY a JSON object, no prose, no markdown fences:
{
  "interpretations": [
    {
      "note_index": 0,
      "applies": true,
      "directive_type": "solar_reduction",
      "structured_adjustment": {"hours": [12, 13], "factor": 0.25},
      "explanation": "short reason"
    }
  ]
}
Return EXACTLY one entry per input note, in note_index order (0, 1, 2, ...).
"""


def _user_prompt(notes: List[str], battery: Dict[str, Any]) -> str:
    numbered = "\n".join(f'{i}. "{n}"' for i, n in enumerate(notes))
    return (
        f"Battery context (use for relative-reserve conversion):\n"
        f"  capacity_kwh = {battery['capacity_kwh']}\n"
        f"  minimum_energy_kwh = {battery['minimum_energy_kwh']}\n\n"
        f"Operator notes:\n{numbered}\n\n"
        f"Return the JSON object described in the system message. "
        f"Exactly {len(notes)} interpretation(s)."
    )


def _extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    return json.loads(text)


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=0.4, max=2))
async def _call_llm(messages: List[Dict[str, str]]) -> str:
    url = f"{settings.LLM_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.LLM_MODEL,
        "messages": messages,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
        "max_tokens": 900,
    }
    async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]


async def interpret_notes(
    notes: List[str], battery: Dict[str, Any]
) -> List[Dict[str, Any]]:
    if not settings.has_llm():
        log.warning("LLM_API_KEY missing — using safe no_op fallback")
        return _fallback_noop(notes)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _user_prompt(notes, battery)},
    ]
    try:
        raw = await _call_llm(messages)
        parsed = _extract_json(raw)
        interps = parsed.get("interpretations")
        if not isinstance(interps, list):
            raise ValueError("interpretations missing or not a list")
        return _normalise_to_notes(interps, notes)
    except Exception as e:  # noqa: BLE001
        log.exception("LLM interpretation failed: %s", e)
        return _fallback_noop(notes)


def _fallback_noop(notes: List[str]) -> List[Dict[str, Any]]:
    return [
        {
            "note_index": i,
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
            "explanation": "Interpretation unavailable; treated as no_op.",
        }
        for i in range(len(notes))
    ]


def _normalise_to_notes(
    interps: List[Dict[str, Any]], notes: List[str]
) -> List[Dict[str, Any]]:
    by_idx: Dict[int, Dict[str, Any]] = {}
    for item in interps:
        if not isinstance(item, dict):
            continue
        idx = item.get("note_index")
        if isinstance(idx, int) and 0 <= idx < len(notes) and idx not in by_idx:
            by_idx[idx] = item
    out = []
    for i in range(len(notes)):
        if i in by_idx:
            out.append(by_idx[i])
        else:
            out.append(
                {
                    "note_index": i,
                    "applies": False,
                    "directive_type": "no_op",
                    "structured_adjustment": None,
                    "explanation": "Note not interpreted; treated as no_op.",
                }
            )
    return out