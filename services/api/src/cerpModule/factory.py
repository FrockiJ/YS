from __future__ import annotations

from ..core.config import (
    CERP_API_KEY_ID,
    CERP_BASE_URL,
    CERP_DEFAULT_COMP_ID,
    CERP_DEFAULT_CUST_ID,
    CERP_DEFAULT_SUPPLIER,
    CERP_TOKEN_REFRESH_BUFFER_SECONDS,
    CERP_TOKEN_TTL_SECONDS,
    YS_CERP_MODE,
)
from .client import CERPClient
from .fake_client import FakeCERPClient


def is_fake_cerp_mode() -> bool:
    return str(YS_CERP_MODE or "").strip().lower() == "fake"


def get_cerp_client():
    if is_fake_cerp_mode():
        return FakeCERPClient()
    return CERPClient(
        base_url=CERP_BASE_URL,
        default_custid=CERP_DEFAULT_CUST_ID,
        default_supplier=CERP_DEFAULT_SUPPLIER,
        default_compid=CERP_DEFAULT_COMP_ID,
        default_apikeyid=CERP_API_KEY_ID,
        token_ttl=CERP_TOKEN_TTL_SECONDS,
        token_refresh_buffer=CERP_TOKEN_REFRESH_BUFFER_SECONDS,
    )
