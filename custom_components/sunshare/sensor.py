"""Sensors for the Sunshare integration.

Three groups:
- Live power flow (`pv_power`, `pv1_power`, `pv2_power`, `output_power`,
  `battery_power`, `load_power`, `grid_power`) from the encrypted
  `systemDiagramUpdate` read (AES-128-ECB, header `encchannel: 1`, gated on an
  open real-time session — see API_DOCUMENTATION.md §3c-FINAL and
  `coordinator.py`). These are the three originally-requested sensors: PV input
  (`pvPow`), current power output (`invPow`), battery in/out (`batPow`,
  NEGATIVE = charging, positive = discharging). They report `None` (become
  "unavailable"), not 0, whenever the device isn't pushing — typically the
  first poll right after opening the session, or while the mobile app holds the
  single allowed session (§2).
- Confirmed static/slow fields (status, RSSI, firmware, SOC limits, lifetime
  stats) — safe to treat as "the real thing".
- Battery pack fields (`battery_soc`, `battery_temperature`,
  `battery_rated_capacity`, `battery_remaining_capacity`) from
  `app/sysDeviceInfo/findBatteryAndDsSsById`, confirmed live + correct: its
  `currentDate` tracks real request time, and SOC/temperature matched an exact
  live app cross-check (see API_DOCUMENTATION.md §3b).

The old `findDeviceListByUserId.power/consumption` and `findById.soc/temp1`
fields were confirmed dead (always 0 / stale placeholders) and are gone —
`systemDiagramUpdate` is the real live source. See API_DOCUMENTATION.md §3c
for the full writeup.
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
    # --- Live power flow (systemDiagramUpdate) — see module docstring ---
    SunshareSensorDescription(
        key="pv_power",
        translation_key="pv_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda d: d.pv_power_w,
    ),
    SunshareSensorDescription(
        key="output_power",
        translation_key="output_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda d: d.output_power_w,
    ),
    SunshareSensorDescription(
        key="battery_power",
        translation_key="battery_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda d: d.battery_power_w,
    ),
    SunshareSensorDescription(
        key="load_power",
        translation_key="load_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda d: d.load_power_w,
    ),
    SunshareSensorDescription(
        key="grid_power",
        translation_key="grid_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda d: d.grid_power_w,
    ),
    SunshareSensorDescription(
        key="pv1_power",
        translation_key="pv1_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.pv1_power_w,
    ),
    SunshareSensorDescription(
        key="pv2_power",
        translation_key="pv2_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.pv2_power_w,
    ),
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
