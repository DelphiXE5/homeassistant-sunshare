"""Data update coordinator for the Sunshare integration."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SunshareApiClient, SunshareApiError, SunshareAuthError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass
class SunshareDevice:
    """Merged view of one device across the endpoints we poll.

    `battery_*` fields come from `findBatteryAndDsSsById` instead — confirmed
    live (its `currentDate` tracks real request time) and confirmed correct
    (`battery_temp_c`/`battery_soc_percent` matched a live app cross-check
    exactly; `battery_rated_capacity_kwh`/`battery_remaining_capacity_kwh`
    match the app's own tooltip strings for `totalPower`/`currentPower`, see
    API_DOCUMENTATION.md §3b). `battery_power_w` (`batPow`) is a plausible
    but NOT confirmed candidate for instantaneous charge/discharge power —
    it stayed at 0 through a 4+ minute test during an active ~200 W
    discharge event, the same flat-zero pattern seen on `raw_power`/
    `raw_consumption` below, so treat it with the same caution.

    `raw_power`/`raw_consumption` mirror `findDeviceListByUserId` fields
    that were originally thought to be live but are now unconfirmed: a
    2026-07-29 test polled them every 8-15s for 4+ minutes during a verified
    ~200 W battery-to-grid discharge event and both stayed at exactly 0 the
    entire time. `findById`'s `soc`/`temp1` were tried too but confirmed
    *dead* (its `updateTime` doesn't move, and real values didn't match
    reality — see API_DOCUMENTATION.md) so they are deliberately not
    surfaced here at all.
    """

    id: int
    sn: str
    name: str
    device_type_dec: str | None
    model: str | None
    brand: str | None
    ota_ver: str | None
    hw_version: str | None
    status_dec: str | None
    rssi: int | None
    country_max_power: int | None
    perm_power: int | None
    soc_min: int | None
    soc_max: int | None
    raw_power: float | None
    raw_consumption: float | None
    battery_soc_percent: float | None
    battery_temp_c: float | None
    battery_rated_capacity_kwh: float | None
    battery_remaining_capacity_kwh: float | None
    battery_power_w: float | None
    lifetime_energy_kwh: float | None
    lifetime_energy_unit: str | None
    today_energy_kwh: float | None
    today_energy_unit: str | None
    lifetime_revenue: float | None
    lifetime_revenue_unit: str | None
    lifetime_co2_kg: float | None
    lifetime_co2_unit: str | None


class SunshareDataUpdateCoordinator(DataUpdateCoordinator[dict[int, SunshareDevice]]):
    """Polls findDeviceListByUserId + findById + queryMesSettingUpdate + selectInveSummary."""

    def __init__(
        self, hass: HomeAssistant, client: SunshareApiClient, update_interval: timedelta
    ) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, update_interval=update_interval
        )
        self.client = client

    async def _async_update_data(self) -> dict[int, SunshareDevice]:
        try:
            devices = await self.client.async_get_devices()
            result: dict[int, SunshareDevice] = {}
            for device in devices:
                device_id = device["id"]
                detail, mes_setting, summary, battery = await asyncio.gather(
                    self.client.async_get_device_detail(device_id),
                    self.client.async_get_mes_setting(device_id),
                    self.client.async_get_summary(device_id),
                    self.client.async_get_battery_status(device_id),
                )
                result[device_id] = _merge_device(
                    device, detail, mes_setting, summary, battery
                )
            return result
        except SunshareAuthError as err:
            raise UpdateFailed(f"Sunshare authentication failed: {err}") from err
        except SunshareApiError as err:
            raise UpdateFailed(f"Sunshare API error: {err}") from err


def _merge_device(
    device: dict, detail: dict, mes_setting: dict, summary: dict, battery: dict
) -> SunshareDevice:
    mes_pojo = mes_setting.get("mesSettingUpdatePojo") or {}
    ems_advan = mes_setting.get("emsModeAdvan") or {}
    # First pack only — fine for this project's single-pack device; a
    # multi-pack system would need averaging mapList[*].temp1 instead.
    battery_pack = (battery.get("mapList") or [{}])[0]

    return SunshareDevice(
        id=device["id"],
        sn=device.get("sn", ""),
        name=device.get("deviceName") or device.get("sn") or f"Sunshare {device['id']}",
        device_type_dec=device.get("deviceTypeDec"),
        model=detail.get("model"),
        brand=detail.get("brand"),
        ota_ver=detail.get("otaVer"),
        hw_version=detail.get("hwVersionNo"),
        status_dec=device.get("statusDec"),
        rssi=device.get("rssi"),
        country_max_power=device.get("countryMaxPower") or detail.get("maxGridPower"),
        perm_power=mes_pojo.get("permPower"),
        soc_min=ems_advan.get("socMin"),
        soc_max=ems_advan.get("socMax"),
        raw_power=device.get("power"),
        raw_consumption=device.get("consumption"),
        battery_soc_percent=_as_percent(battery.get("socPer")),
        battery_temp_c=_as_float(battery_pack.get("temp1")),
        battery_rated_capacity_kwh=_as_float(battery.get("totalPower")),
        battery_remaining_capacity_kwh=_as_float(battery.get("currentPower")),
        battery_power_w=_as_float(battery.get("batPow")),
        lifetime_energy_kwh=summary.get("totalAllPower"),
        lifetime_energy_unit=summary.get("totalAllPowerUnit"),
        today_energy_kwh=summary.get("dayPower"),
        today_energy_unit=summary.get("dayPowerUnit"),
        lifetime_revenue=_as_float(summary.get("totalAllPrice")),
        lifetime_revenue_unit=summary.get("totalAllPriceUnit"),
        lifetime_co2_kg=summary.get("accuCo2Redu"),
        lifetime_co2_unit=summary.get("accuCo2ReduUnit"),
    )


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_percent(value: object) -> float | None:
    """Parse Sunshare's "20%"-style percent strings into a plain float."""
    if isinstance(value, str):
        value = value.rstrip("%")
    return _as_float(value)
