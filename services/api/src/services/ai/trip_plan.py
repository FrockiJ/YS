from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, Optional


def _empty_trip_plan() -> Dict[str, Any]:
    return {
        "activity": None,
        "destination_region": None,
        "departure_location": None,
        "elevation_band": None,
        "duration_days": None,
        "travel_constraints": [],
        "candidate_destinations": [],
        "selected_destination": None,
        "active_task_type": "knowledge",
    }


@dataclass(frozen=True)
class TripPlanResult:
    trip_plan: Dict[str, Any]
    changed: bool


class TripPlanService:
    """Stores planner-produced trip facts; it does not classify user text."""

    def merge_planner_patch(
        self,
        *,
        context_state: Optional[Dict[str, Any]],
        patch: Optional[Dict[str, Any]],
        task_type: str,
    ) -> TripPlanResult:
        plan = copy.deepcopy(self.from_context(context_state))
        before = copy.deepcopy(plan)
        allowed = {
            "activity",
            "destination_region",
            "departure_location",
            "elevation_band",
            "duration_days",
            "travel_constraints",
            "candidate_destinations",
            "selected_destination",
        }
        for key, value in (patch or {}).items():
            if key not in allowed or value in (None, "", [], {}):
                continue
            if key == "duration_days":
                try:
                    value = max(1, min(int(value), 365))
                except (TypeError, ValueError):
                    continue
            plan[key] = copy.deepcopy(value)
        plan["active_task_type"] = str(task_type or "knowledge")
        return TripPlanResult(plan, plan != before)

    @staticmethod
    def from_context(context_state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(context_state, dict) or not isinstance(context_state.get("trip_plan"), dict):
            return _empty_trip_plan()
        plan = _empty_trip_plan()
        for key in plan:
            value = context_state["trip_plan"].get(key)
            if value not in (None, ""):
                plan[key] = copy.deepcopy(value)
        return plan

    @staticmethod
    def has_trip_context(plan: Dict[str, Any]) -> bool:
        return any(
            plan.get(key) not in (None, "", [], {})
            for key in (
                "activity",
                "destination_region",
                "departure_location",
                "elevation_band",
                "duration_days",
                "travel_constraints",
                "candidate_destinations",
                "selected_destination",
            )
        )
