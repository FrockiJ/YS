import json
import os
from functools import lru_cache
from typing import Any, Dict

DEFAULT_STORE_PROFILE_PATH = os.getenv(
    "STORE_PROFILE_PATH",
    os.path.join(os.path.dirname(__file__), "../../store_profile.json"),
)


@lru_cache(maxsize=1)
def get_store_profile() -> Dict[str, Any]:
    path = DEFAULT_STORE_PROFILE_PATH
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            if not isinstance(data, dict):
                raise ValueError("Store profile must be a JSON object")
            return data
    except FileNotFoundError:
        return {}
    except Exception as exc:
        return {"error": f"Failed to load store profile: {exc}"}
