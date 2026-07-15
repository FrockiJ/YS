from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional


_CAMPSITE_RE = re.compile(r"(?:營區|營地|露營區|露營地|campgrounds?|campsites?)", re.IGNORECASE)
_FILTER_RE = re.compile(r"(?:篩選|過濾|縮小|依.+出發|從.+出發|filter|narrow\s+down)", re.IGNORECASE)
_TOPIC_SHIFT_RE = re.compile(
    r"(?:換個話題|換話題|另外一件事|不談這個|重新開始)|\b(?:new topic|change topic|start over)\b",
    re.IGNORECASE,
)

_REGIONS = (
    ("southern_taiwan", ("南部", "南台灣", "南臺灣", "southern taiwan")),
    ("central_taiwan", ("中部", "中台灣", "中臺灣", "central taiwan")),
    ("northern_taiwan", ("北部", "北台灣", "北臺灣", "northern taiwan")),
    ("eastern_taiwan", ("東部", "東台灣", "東臺灣", "eastern taiwan")),
)
_ELEVATIONS = (
    ("mid_altitude", ("中海拔", "mid-altitude", "mid altitude")),
    ("high_altitude", ("高海拔", "high-altitude", "high altitude")),
    ("low_altitude", ("低海拔", "low-altitude", "low altitude")),
)
_REGION_LABELS = {
    "southern_taiwan": "南部",
    "central_taiwan": "中部",
    "northern_taiwan": "北部",
    "eastern_taiwan": "東部",
}
_ELEVATION_LABELS = {
    "mid_altitude": "中海拔",
    "high_altitude": "高海拔",
    "low_altitude": "低海拔",
}


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
    """Maintains traceable trip facts separately from ERP product needs."""

    def update(
        self,
        message: str,
        *,
        context_state: Optional[Dict[str, Any]],
        task_type: str,
    ) -> TripPlanResult:
        text = str(message or "").strip()
        prior = self.from_context(context_state)
        plan = _empty_trip_plan() if _TOPIC_SHIFT_RE.search(text) else copy.deepcopy(prior)
        before = copy.deepcopy(plan)

        campsite_context = bool(_CAMPSITE_RE.search(text)) or bool(plan.get("activity") == "camping")
        if campsite_context and task_type in {
            "destination_recommendation",
            "destination_filter",
            "product_recommendation",
            "erp_lookup",
        }:
            plan["activity"] = "camping"

        region = self._match_label(text, _REGIONS)
        if region:
            plan["destination_region"] = region
        elevation = self._match_label(text, _ELEVATIONS)
        if elevation:
            plan["elevation_band"] = elevation
        departure = self._extract_departure(text)
        if departure:
            plan["departure_location"] = departure
        duration_days = self._extract_duration_days(text)
        if duration_days:
            plan["duration_days"] = duration_days

        if task_type in {
            "destination_recommendation",
            "destination_filter",
            "product_recommendation",
            "erp_lookup",
        }:
            plan["active_task_type"] = task_type
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

    @classmethod
    def to_product_need_patch(cls, plan: Dict[str, Any]) -> Dict[str, Any]:
        if not cls.has_trip_context(plan) or plan.get("activity") != "camping":
            return {}
        destination = "".join(
            part
            for part in (
                _REGION_LABELS.get(str(plan.get("destination_region") or ""), ""),
                _ELEVATION_LABELS.get(str(plan.get("elevation_band") or ""), ""),
            )
            if part
        )
        patch: Dict[str, Any] = {
            "activity": "camping",
            "categories": [
                "shelter",
                "sleeping_gear",
                "lighting",
                "cooking_water",
                "storage_packs",
                "power",
                "safety_repair",
            ],
        }
        if destination:
            patch["location"] = destination
        duration_days = plan.get("duration_days")
        if isinstance(duration_days, int) and duration_days > 0:
            patch["duration"] = f"{duration_days}天"
        return patch

    @classmethod
    def apply_product_context(
        cls,
        profile: Dict[str, Any],
        plan: Dict[str, Any],
        message: str,
    ) -> Dict[str, Any]:
        """Use saved trip facts for omitted product context without leaking enum codes."""
        result = copy.deepcopy(profile or {})
        patch = cls.to_product_need_patch(plan)
        if not patch:
            return result
        text = str(message or "")
        has_activity_override = bool(
            re.search(r"(?:登山|健行|爬山|露營|野營|釣魚|hiking|camping|fishing)", text, re.IGNORECASE)
        )
        has_destination_override = bool(
            cls._match_label(text, _REGIONS)
            or cls._match_label(text, _ELEVATIONS)
            or re.search(r"(?:玉山|雪山|合歡山|阿里山|太魯閣|陽明山|[\u4e00-\u9fff]{2,8}(?:市|縣))", text)
        )
        has_duration_override = cls._extract_duration_days(text) is not None
        if not has_activity_override and patch.get("activity"):
            result["activity"] = patch["activity"]
        if not has_destination_override and patch.get("location"):
            result["location"] = patch["location"]
        if not has_duration_override and patch.get("duration"):
            result["duration"] = patch["duration"]
        categories = list(result.get("categories") or [])
        seen = {str(item).casefold() for item in categories}
        for category in patch.get("categories") or []:
            if str(category).casefold() not in seen:
                categories.append(category)
                seen.add(str(category).casefold())
        result["categories"] = categories
        return result

    @classmethod
    def retrieval_query(cls, message: str, plan: Dict[str, Any], task_type: str) -> Optional[str]:
        if task_type not in {"destination_recommendation", "destination_filter"}:
            return None
        details = []
        region = _REGION_LABELS.get(str(plan.get("destination_region") or ""))
        elevation = _ELEVATION_LABELS.get(str(plan.get("elevation_band") or ""))
        if region:
            details.append(region)
        if elevation:
            details.append(elevation)
        if plan.get("departure_location"):
            details.append(f"從{plan['departure_location']}出發")
        if plan.get("duration_days"):
            details.append(f"{plan['duration_days']}天")
        details.append("露營營地")
        suffix = " ".join(details)
        text = str(message or "").strip()
        return f"{text}；條件：{suffix}" if suffix else text

    @staticmethod
    def is_destination_query(message: str) -> bool:
        return bool(_CAMPSITE_RE.search(str(message or "")))

    @staticmethod
    def is_destination_filter(message: str) -> bool:
        return bool(_FILTER_RE.search(str(message or "")))

    @staticmethod
    def _match_label(text: str, values) -> Optional[str]:
        lowered = text.casefold()
        for label, aliases in values:
            if any(alias.casefold() in lowered for alias in aliases):
                return label
        return None

    @staticmethod
    def _extract_departure(text: str) -> Optional[str]:
        patterns = (
            r"(?:依|以|從)\s*([\u4e00-\u9fff]{2,8})\s*(?:為)?出發地",
            r"從\s*([\u4e00-\u9fff]{2,8})\s*出發",
            r"departure\s+(?:from\s+)?([A-Za-z][A-Za-z .-]{1,30})",
        )
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    @staticmethod
    def _extract_duration_days(text: str) -> Optional[int]:
        match = re.search(r"(\d+)\s*(?:天|日|days?)", text, re.IGNORECASE)
        if match:
            return int(match.group(1))
        chinese = re.search(r"([一二兩三四五六七八九十])\s*(?:天|日)", text)
        if not chinese:
            return None
        values = {"一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        return values.get(chinese.group(1))
