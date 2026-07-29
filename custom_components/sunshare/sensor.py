"""Sensors for the Sunshare integration.

Three groups:
- Confirmed fields (status, RSSI, firmware, SOC limits, lifetime stats) —
  safe to treat as "the real thing".
- Battery fields (`battery_soc`, `battery_temperature`,
  `battery_rated_capacity`, `battery_remaining_capacity`, `battery_power`)
  come from `app/sysDeviceInfo/findBatteryAndDsSsById`, found via string-pool
  analysis (not in the original API_DOCUMENTATION.md). SOC/temperature/
  capacity are confirmed live + correct: its `currentDate` tracks real
  request time, and SOC/temperature matched an exact live app cross-check
  (see API_DOCUMENTATION.md §3b). `battery_power` (`batPow`) is NOT
  confirmed live — a 2026-07-29 test during a verified ~200 W battery
  discharge event had it stuck at 0 the whole time, same as `raw_power`/
  `raw_consumption` below. Kept as a sensor (plausible candidate, right
  unit/identity) but don't trust it yet.
- `raw_power`/`raw_consumption` — thought to be live originally, but a
  2026-07-29 test (polled every 8-15s for 4+ minutes during a verified
  ~200 W battery-to-grid discharge) had both stuck at exactly 0 throughout.
  **No confirmed source for a true live "current output"/"PV input"
  reading exists yet** — the account holder also confirmed the app's own
  homescreen wattage figure stays perfectly fixed even while real output
  changes, meaning it's most likely displaying `permPower` (the target
  setting, see `number.py`) rather than a live measurement. Kept as
  diagnostic sensors in case a longer refresh cycle or different condition
  (e.g. charging) reveals movement — watch these in HA's history.

`findById`'s `soc`/`temp1` fields were tried first (before
`findBatteryAndDsSsById` was found) but are dead placeholders — its
`updateTime` doesn't move and its values didn't match reality — so they are
deliberately not surfaced here. See API_DOCUMENTATION.md for the full
writeup.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import DOMAIN
from .coordinator import SunshareDataUpdateCoordinator, SunshareDevice
from .entity import SunshareEntity


@dataclass(frozen=True, kw_only=True)
class SunshareSensorDescription(SensorEntityDescription):
    """A SensorEntityDescription with a getter and (optionally) dynamic unit."""

    value_fn: Callable[[SunshareDevice], StateType]
    unit_fn: Callable[[SunshareDevice], str | None] | None = None


SENSOR_DESCRIPTIONS: tuple[SunshareSensorDescription, ...] = (
    SunshareSensorDescription(
        key="status",
        translation_key="status",
        value_fn=lambda d: d.status_dec,
    ),
    SunshareSensorDescription(
        key="rssi",
        translation_key="rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement="dBm",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.rssi,
    ),
    SunshareSensorDescription(
        key="firmware_version",
        translation_key="firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.ota_ver,
    ),
    SunshareSensorDescription(
        key="country_max_power",
        translation_key="country_max_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.country_max_power,
    ),
    SunshareSensorDescription(
        key="soc_min",
        translation_key="soc_min",
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.soc_min,
    ),
    SunshareSensorDescription(
        key="soc_max",
        translation_key="soc_max",
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.soc_max,
    ),
    SunshareSensorDescription(
        key="lifetime_energy",
        translation_key="lifetime_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="kWh",
        value_fn=lambda d: d.lifetime_energy_kwh,
    ),
    SunshareSensorDescription(
        key="today_energy",
        translation_key="today_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="kWh",
        value_fn=lambda d: d.today_energy_kwh,
    ),
    SunshareSensorDescription(
        key="lifetime_revenue",
        translation_key="lifetime_revenue",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: d.lifetime_revenue,
        unit_fn=lambda d: d.lifetime_revenue_unit,
    ),
    SunshareSensorDescription(
        key="lifetime_co2_saved",
        translation_key="lifetime_co2_saved",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: d.lifetime_co2_kg,
        unit_fn=lambda d: d.lifetime_co2_unit or "kg",
    ),
    # --- Battery telemetry (findBatteryAndDsSsById) — see module docstring ---
    SunshareSensorDescription(
        key="battery_soc",
        translation_key="battery_soc",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda d: d.battery_soc_percent,
    ),
    SunshareSensorDescription(
        key="battery_temperature",
        translation_key="battery_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.battery_temp_c,
    ),
    SunshareSensorDescription(
        key="battery_remaining_capacity",
        translation_key="battery_remaining_capacity",
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="kWh",
        value_fn=lambda d: d.battery_remaining_capacity_kwh,
    ),
    SunshareSensorDescription(
        key="battery_rated_capacity",
        translation_key="battery_rated_capacity",
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="kWh",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.battery_rated_capacity_kwh,
    ),
    SunshareSensorDescription(
        key="battery_power",
        translation_key="battery_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda d: d.battery_power_w,
    ),
    # --- Raw / unconfirmed fields — see module docstring ---
    SunshareSensorDescription(
        key="raw_power",
        translation_key="raw_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.raw_power,
    ),
    SunshareSensorDescription(
        key="raw_consumption",
        translation_key="raw_consumption",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.raw_consumption,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: SunshareDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        SunshareSensor(coordinator, device_id, description)
        for device_id in coordinator.data
        for description in SENSOR_DESCRIPTIONS
    )


class SunshareSensor(SunshareEntity, SensorEntity):
    entity_description: SunshareSensorDescription

    def __init__(
        self,
        coordinator: SunshareDataUpdateCoordinator,
        device_id: int,
        description: SunshareSensorDescription,
    ) -> None:
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def native_value(self) -> StateType:
        device = self.device
        if device is None:
            return None
        return self.entity_description.value_fn(device)

    @property
    def native_unit_of_measurement(self) -> str | None:
        device = self.device
        if self.entity_description.unit_fn and device is not None:
            return self.entity_description.unit_fn(device)
        return self.entity_description.native_unit_of_measurement
