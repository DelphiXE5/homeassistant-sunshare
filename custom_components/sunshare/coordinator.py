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

    Live power fields (`pv_power_w`, `pv1/pv2_power_w`, `output_power_w`,
    `battery_power_w`, `load_power_w`, `grid_power_w`) come from the encrypted
    `systemDiagramUpdate` read (AES-128-ECB, header `encchannel: 1`, gated on
    an open real-time session) — the definitive live source, verified
    end-to-end from standalone code (API_DOCUMENTATION.md §3c-FINAL). These are
    the three originally-requested sensors: PV input (`pvPow`), current output
    (`invPow`), battery flow (`batPow`, NEGATIVE = charging). They read `None`
    (not 0) whenever the device isn't currently pushing — e.g. the very first
    poll right after the session is opened, or while the mobile app has taken
    the single allowed session (§2).

    Battery pack fields (`battery_soc_percent`, `battery_temp_c`,
    `battery_*_capacity_kwh`) come from `findBatteryAndDsSsById` — confirmed
    live (its `currentDate` tracks real request time) and correct (SOC/temp
    matched a live app cross-check exactly; capacities match the app's own
    tooltip strings for `totalPower`/`currentPower`, see §3b).

    Note: the old `findDeviceListByUserId.power/consumption` and
    `findById.soc/temp1` fields were confirmed *dead* (always 0 / stale
    placeholders across three real conditions on 2026-07-29) and are
    deliberately not surfaced — `systemDiagramUpdate` replaces them.
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
    pv_power_w: float | None
    pv1_power_w: float | None
    pv2_power_w: float | None
    output_power_w: float | None
    battery_power_w: float | None
    load_power_w: float | None
    grid_power_w: float | None
    battery_soc_percent: float | None
    battery_temp_c: float | None
    battery_rated_capacity_kwh: float | None
    battery_remaining_capacity_kwh: float | None
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
                flow = await self._async_get_live_flow(device_id, device.get("sn"))
                result[device_id] = _merge_device(
                    device, detail, mes_setting, summary, battery, flow
                )
            return result
        except SunshareAuthError as err:
            raise UpdateFailed(f"Sunshare authentication failed: {err}") from err
        except SunshareApiError as err:
            raise UpdateFailed(f"Sunshare API error: {err}") from err

    async def _async_get_live_flow(
        self, device_id: int, sn: str | None
    ) -> dict:
        """Trigger + read the encrypted live power flow, best-effort.

        The live read depends on the device currently pushing (an open
        real-time session, which also contends with the mobile app for the
        single allowed session). A failure here must not fail the whole
        update — the confirmed fields still poll fine — so any error just
        yields empty live values for this cycle.
        """
        if not sn:
            return {}
        try:
            await self.client.async_open_realtime(device_id)
            return await self.client.async_get_live_flow(device_id, sn)
        except SunshareApiError as err:
            _LOGGER.debug("Live flow unavailable for device %s: %s", device_id, err)
            return {}


def _merge_device(
    device: dict, detail: dict, mes_setting: dict, summary: dict, battery: dict,
    flow: dict,
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
        pv_power_w=_as_float(flow.get("pvPow")),
        pv1_power_w=_as_float(flow.get("pv1Pow")),
        pv2_power_w=_as_float(flow.get("pv2Pow")),
        output_power_w=_as_float(flow.get("invPow")),
        battery_power_w=_as_float(flow.get("batPow")),
        load_power_w=_as_float(flow.get("loadPow")),
        grid_power_w=_as_float(flow.get("gridPow")),
        battery_soc_percent=_as_percent(battery.get("socPer")),
        battery_temp_c=_as_float(battery_pack.get("temp1")),
        battery_rated_capacity_kwh=_as_float(battery.get("totalPower")),
        battery_remaining_capacity_kwh=_as_float(battery.get("currentPower")),
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
