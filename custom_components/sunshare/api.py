"""Thin async client for the Sunshare (Sunsharetek) cloud REST API.

See API_DOCUMENTATION.md in the repo root for how every endpoint here was
reverse-engineered and confirmed. Only the endpoints documented as
[CONFIRMED] there are used.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from .const import (
    BASE_URL,
    PATH_BATTERY_STATUS,
    PATH_DEVICE_DETAIL,
    PATH_DEVICE_LIST,
    PATH_LOGIN,
    PATH_MES_SETTING,
    PATH_SUMMARY,
    PATH_UPDATE_EMS_PARA,
)

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)


class SunshareApiError(Exception):
    """Generic Sunshare API error (non-200 `code`, network failure, etc.)."""


class SunshareAuthError(SunshareApiError):
    """Login failed, or the session token was rejected and re-login also failed."""


class SunshareApiClient:
    """Talks to https://web.sunsharetek.com/app/.

    Handles the single-session-per-account quirk (§2 of API_DOCUMENTATION.md):
    logging in elsewhere (e.g. the mobile app) invalidates our token, so every
    call transparently re-logs-in once on an auth failure and retries.
    """

    def __init__(
        self, session: aiohttp.ClientSession, user_account: str, password: str
    ) -> None:
        self._session = session
        self._user_account = user_account
        self._password = password
        self._token: str | None = None
        self._login_lock = asyncio.Lock()

    async def async_login(self) -> None:
        """Log in and cache the access token. Raises SunshareAuthError on failure."""
        async with self._login_lock:
            await self._async_login_locked()

    async def _async_login_locked(self) -> None:
        url = BASE_URL + PATH_LOGIN
        body = {"userAccount": self._user_account, "password": self._password}
        try:
            async with self._session.post(
                url, json=body, headers=_headers(), timeout=REQUEST_TIMEOUT
            ) as resp:
                data = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise SunshareApiError(f"Login request failed: {err}") from err

        if not isinstance(data, dict) or data.get("code") != 200:
            msg = data.get("msg") if isinstance(data, dict) else None
            raise SunshareAuthError(msg or "Login rejected by Sunshare API")

        token = (data.get("data") or {}).get("access_token")
        if not token:
            raise SunshareAuthError("Login response did not contain an access token")
        self._token = token

    async def _async_call(self, path: str, body: dict[str, Any]) -> Any:
        """POST an authenticated call, re-logging-in once on auth failure."""
        if self._token is None:
            await self.async_login()

        data = await self._async_post(path, body)
        if _is_auth_error(data):
            _LOGGER.debug("Sunshare token rejected, re-authenticating")
            await self.async_login()
            data = await self._async_post(path, body)
            if _is_auth_error(data):
                raise SunshareAuthError("Re-authentication did not restore access")

        if not isinstance(data, dict) or data.get("code") != 200:
            msg = data.get("msg") if isinstance(data, dict) else None
            raise SunshareApiError(f"{path} failed: {msg or data}")

        return data.get("data")

    async def _async_post(self, path: str, body: dict[str, Any]) -> Any:
        url = BASE_URL + path
        headers = _headers()
        if self._token:
            headers["Authorization"] = self._token
        try:
            async with self._session.post(
                url, json=body, headers=headers, timeout=REQUEST_TIMEOUT
            ) as resp:
                return await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise SunshareApiError(f"{path} request failed: {err}") from err

    async def async_get_devices(self) -> list[dict[str, Any]]:
        """POST app/sysDeviceInfo/findDeviceListByUserId — device list w/ live power/status."""
        data = await self._async_call(PATH_DEVICE_LIST, {})
        return data or []

    async def async_get_device_detail(self, device_id: int) -> dict[str, Any]:
        """POST app/sysDeviceInfo/findById — full device entity."""
        data = await self._async_call(PATH_DEVICE_DETAIL, {"id": device_id})
        return data or {}

    async def async_get_mes_setting(self, device_id: int) -> dict[str, Any]:
        """POST app/sysDeviceInfo/queryMesSettingUpdate — structured EMS/power settings."""
        data = await self._async_call(PATH_MES_SETTING, {"deviceId": device_id})
        return data or {}

    async def async_get_summary(self, device_id: int) -> dict[str, Any]:
        """POST app/inveRealDataMinute/selectInveSummary — lifetime generation/revenue/CO2."""
        data = await self._async_call(PATH_SUMMARY, {"deviceId": device_id})
        return data or {}

    async def async_get_battery_status(self, device_id: int) -> dict[str, Any]:
        """POST app/sysDeviceInfo/findBatteryAndDsSsById — live battery pack telemetry.

        Found via string-pool analysis (not in the original API_DOCUMENTATION.md),
        then confirmed genuinely live: the response's own `currentDate` field
        matches the real request time, and its `soc`/`temp1` values matched a
        live app cross-check exactly (see API_DOCUMENTATION.md §3b). Body key
        is "id" (matching findById), not "deviceId" like the other calls here.
        """
        data = await self._async_call(PATH_BATTERY_STATUS, {"id": device_id})
        return data or {}

    async def async_set_output_power(
        self, device_id: int, watts: int, ems_strategy_type: int = 1
    ) -> None:
        """POST app/sysDeviceInfo/updateEmsParaById — the confirmed wattage-control call.

        Body must be wrapped under "mesSettingUpdatePojo" — see
        API_DOCUMENTATION.md §6 for why the flat/unwrapped shape 500s.
        """
        body = {
            "mesSettingUpdatePojo": {
                "emsStrategyType": ems_strategy_type,
                "permPower": watts,
                "powerSetPojos": [],
                "deviceId": device_id,
                "isOnlySave": 0,
            }
        }
        result = await self._async_call(PATH_UPDATE_EMS_PARA, body)
        if result is not True:
            raise SunshareApiError(f"updateEmsParaById did not confirm success: {result}")


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "language": "en",
        "localeName": "en",
    }


def _is_auth_error(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    code = data.get("code")
    if code in (401, 403):
        return True
    msg = (data.get("msg") or "")
    return isinstance(msg, str) and any(
        needle in msg.lower() for needle in ("token", "unauthor", "login", "expired")
    )
