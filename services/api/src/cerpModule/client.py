import asyncio
import time
from typing import Any, Dict, Iterable, Mapping, Optional, Union

import httpx


class CERPClientError(Exception):
    """Raised when the CERP integration cannot complete."""


class CERPClient:
    def __init__(
        self,
        *,
        base_url: str,
        default_custid: Optional[str] = None,
        default_supplier: Optional[str] = None,
        default_compid: Optional[str] = None,
        default_apikeyid: Optional[str] = None,
        token_ttl: int = 604_800,
        token_refresh_buffer: int = 300,
        verify: Optional[Union[bool, str]] = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_custid = default_custid
        self.default_supplier = default_supplier
        self.default_compid = default_compid
        self.default_apikeyid = default_apikeyid
        self._token: Optional[str] = None
        self._token_expiry = 0.0
        self._token_lock = asyncio.Lock()
        self.token_ttl = token_ttl
        self._token_refresh_buffer = token_refresh_buffer
        self._verify = verify

        # CERP paths discovered from the documentation.
        self.login_path = "/CerpHook/sys/eLoginToken"
        self.product_path = "/CerpHook/in/ExportProduct"
        self.warehouse_path = "/CerpHook/in/ExportWarehouse"
        self.product_info_path = "/CerpHook/in/ExportProductsInfo"

    def _build_url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    @staticmethod
    def _filter_none(payload: Mapping[str, Any]) -> Dict[str, Any]:
        return {key: value for key, value in payload.items() if value not in (None, [], {})}

    async def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = self._build_url(path)
        async with httpx.AsyncClient(timeout=30.0, verify=self._verify) as client:
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise CERPClientError(f"CERP request failed for {url}: {exc}") from exc
            try:
                return response.json()
            except ValueError as exc:
                raise CERPClientError(f"Unable to parse CERP response from {url}: {exc}") from exc

    def _resolve_credential(self, provided: Optional[str], default: Optional[str], name: str) -> str:
        if provided:
            return provided
        if default:
            return default
        raise CERPClientError(f"Missing CERP credential `{name}`. Provide it via the request or environment.")

    def _extract_token(self, payload: Any) -> str:
        if isinstance(payload, str) and payload.strip():
            return payload.strip()
        if isinstance(payload, Mapping):
            for key in ("token", "Token", "TOKEN", "GUID", "guid"):
                raw = payload.get(key)
                if isinstance(raw, str) and raw.strip():
                    return raw.strip()
            # Some responses wrap token inside nested `data`.
            inner = payload.get("data")
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
        if isinstance(payload, Iterable):
            for item in payload:
                if isinstance(item, str) and item.strip():
                    return item.strip()
                if isinstance(item, Mapping):
                    for key in ("token", "Token", "TOKEN", "guid"):
                        raw = item.get(key)
                        if isinstance(raw, str) and raw.strip():
                            return raw.strip()
        raise CERPClientError("CERP token not found in login response.")

    @staticmethod
    def _status_ok(response: Mapping[str, Any]) -> bool:
        status = str(response.get("status", "")).strip()
        return not status or status == "200"

    @staticmethod
    def _status_error(response: Mapping[str, Any]) -> str:
        return f"status={response.get('status')}, errors={response.get('errors')}"

    @staticmethod
    def _looks_like_token_error(response: Mapping[str, Any]) -> bool:
        errors = response.get("errors")
        if isinstance(errors, list):
            text = " ".join(str(item) for item in errors)
        else:
            text = str(errors or "")
        lowered = text.lower()
        return any(
            marker in lowered
            for marker in ("token", "通行碼", "鑰匙key", "鑰匙 key", "key")
        )

    def _clear_token(self) -> None:
        self._token = None
        self._token_expiry = 0.0

    async def _post_export_with_token(
        self,
        path: str,
        payload: Dict[str, Any],
        credentials: Dict[str, str],
    ) -> Dict[str, Any]:
        response = await self._post(path, payload)
        if self._status_ok(response):
            return response

        if self._looks_like_token_error(response):
            self._clear_token()
            retry_payload = dict(payload)
            retry_payload["TOKEN"] = await self.get_token(credentials)
            response = await self._post(path, retry_payload)
            if self._status_ok(response):
                return response

        raise CERPClientError(f"CERP request failed for {path}: {self._status_error(response)}")

    async def _refresh_token(self, credentials: Dict[str, str]) -> str:
        payload = self._filter_none(credentials)
        response = await self._post(self.login_path, payload)
        status = str(response.get("status", "")).strip()
        if status and status != "200":
            raise CERPClientError(
                f"CERP login failed (status={status}, errors={response.get('errors')})"
            )
        data_payload = response.get("data")
        token = self._extract_token(data_payload)
        self._token = token
        self._token_expiry = time.time() + self.token_ttl - self._token_refresh_buffer
        return token

    async def get_token(self, credentials: Dict[str, str]) -> str:
        now = time.time()
        if self._token and now < self._token_expiry:
            return self._token
        async with self._token_lock:
            now = time.time()
            if self._token and now < self._token_expiry:
                return self._token
            return await self._refresh_token(credentials)

    @staticmethod
    def _normalize_paramchar(value: Optional[Mapping[str, Any]]) -> Optional[Dict[str, list]]:
        if not value:
            return None
        normalized: Dict[str, list] = {}
        for key, raw in value.items():
            if raw is None:
                continue
            if isinstance(raw, list):
                normalized[key] = raw
            else:
                normalized[key] = [raw]
        return normalized or None

    def _build_credentials(
        self,
        *,
        custid: Optional[str],
        supplier: Optional[str],
        compid: Optional[str],
        apikeyid: Optional[str],
    ) -> Dict[str, str]:
        apikeyid = self._resolve_credential(apikeyid, self.default_apikeyid, "apikeyid")
        return {
            "custid": self._resolve_credential(custid, self.default_custid, "custid"),
            "supplier": self._resolve_credential(supplier, self.default_supplier, "supplier"),
            "compid": self._resolve_credential(compid, self.default_compid, "compid"),
            "apikeyid": apikeyid,
        }

    async def export_products(
        self,
        *,
        custid: Optional[str],
        supplier: Optional[str],
        compid: Optional[str],
        exprange: Optional[int] = None,
        lasttime: Optional[str] = None,
        paramchar1: Optional[Mapping[str, Any]] = None,
        invn002b: Optional[str] = None,
        invn002e: Optional[str] = None,
        invn053b: Optional[Union[int, float]] = None,
        invn053e: Optional[Union[int, float]] = None,
        invn013b: Optional[Union[int, float]] = None,
        invn013e: Optional[Union[int, float]] = None,
        page: Optional[int] = None,
        perpage: Optional[int] = None,
    ) -> Dict[str, Any]:
        credentials = self._build_credentials(
            custid=custid,
            supplier=supplier,
            compid=compid,
            apikeyid=None,
        )
        token = await self.get_token(credentials)
        payload: Dict[str, Any] = {"TOKEN": token, "custid": credentials["custid"], "compid": credentials["compid"]}
        if exprange is not None:
            payload["exprange"] = exprange
        if lasttime:
            payload["lasttime"] = lasttime
        paramchar = self._normalize_paramchar(paramchar1)
        if paramchar:
            payload["paramchar1"] = paramchar
        if invn002b:
            payload["invn002b"] = invn002b
        if invn002e:
            payload["invn002e"] = invn002e
        if invn053b is not None:
            payload["invn053b"] = invn053b
        if invn053e is not None:
            payload["invn053e"] = invn053e
        if invn013b is not None:
            payload["invn013b"] = invn013b
        if invn013e is not None:
            payload["invn013e"] = invn013e
        if page:
            payload["page"] = page
        if perpage:
            payload["perpage"] = perpage
        return await self._post_export_with_token(self.product_path, payload, credentials)

    async def export_products_info(
        self,
        *,
        custid: Optional[str],
        supplier: Optional[str],
        compid: Optional[str],
        exprange: Optional[int] = None,
        lasttime: Optional[str] = None,
        paramchar1: Optional[Mapping[str, Any]] = None,
        invn002b: Optional[str] = None,
        invn002e: Optional[str] = None,
        invn030b: Optional[str] = None,
        invn030e: Optional[str] = None,
        invn008b: Optional[str] = None,
        invn008e: Optional[str] = None,
        invn053b: Optional[Union[int, float]] = None,
        invn053e: Optional[Union[int, float]] = None,
        invn013b: Optional[Union[int, float]] = None,
        invn013e: Optional[Union[int, float]] = None,
        page: Optional[int] = None,
        perpage: Optional[int] = None,
    ) -> Dict[str, Any]:
        credentials = self._build_credentials(
            custid=custid,
            supplier=supplier,
            compid=compid,
            apikeyid=None,
        )
        token = await self.get_token(credentials)
        payload: Dict[str, Any] = {
            "TOKEN": token,
            "custid": credentials["custid"],
            "compid": credentials["compid"],
        }
        if exprange is not None:
            payload["exprange"] = exprange
        if lasttime:
            payload["lasttime"] = lasttime
        paramchar = self._normalize_paramchar(paramchar1)
        if paramchar:
            payload["paramchar1"] = paramchar
        if invn002b:
            payload["invn002b"] = invn002b
        if invn002e:
            payload["invn002e"] = invn002e
        if invn030b:
            payload["invn030b"] = invn030b
        if invn030e:
            payload["invn030e"] = invn030e
        if invn008b:
            payload["invn008b"] = invn008b
        if invn008e:
            payload["invn008e"] = invn008e
        if invn053b is not None:
            payload["invn053b"] = invn053b
        if invn053e is not None:
            payload["invn053e"] = invn053e
        if invn013b is not None:
            payload["invn013b"] = invn013b
        if invn013e is not None:
            payload["invn013e"] = invn013e
        if page:
            payload["page"] = page
        if perpage:
            payload["perpage"] = perpage
        return await self._post_export_with_token(self.product_info_path, payload, credentials)

    async def export_warehouses(
        self,
        *,
        custid: Optional[str],
        supplier: Optional[str],
        compid: Optional[str],
        exprange: Optional[int] = None,
        lasttime: Optional[str] = None,
        paramchar1: Optional[Mapping[str, Any]] = None,
        inv1002b: Optional[str] = None,
        inv1002e: Optional[str] = None,
        inv1003b: Optional[str] = None,
        inv1003e: Optional[str] = None,
        page: Optional[int] = None,
        perpage: Optional[int] = None,
    ) -> Dict[str, Any]:
        credentials = self._build_credentials(
            custid=custid,
            supplier=supplier,
            compid=compid,
            apikeyid=None,
        )
        token = await self.get_token(credentials)
        payload: Dict[str, Any] = {"TOKEN": token, "custid": credentials["custid"], "compid": credentials["compid"]}
        if exprange is not None:
            payload["exprange"] = exprange
        if lasttime:
            payload["lasttime"] = lasttime
        paramchar = self._normalize_paramchar(paramchar1)
        if paramchar:
            payload["paramchar1"] = paramchar
        if inv1002b:
            payload["inv1002b"] = inv1002b
        if inv1002e:
            payload["inv1002e"] = inv1002e
        if inv1003b:
            payload["inv1003b"] = inv1003b
        if inv1003e:
            payload["inv1003e"] = inv1003e
        if page:
            payload["page"] = page
        if perpage:
            payload["perpage"] = perpage
        return await self._post_export_with_token(self.warehouse_path, payload, credentials)
