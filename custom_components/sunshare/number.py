"""The inverter's constant output-power control — the main actor of this integration."""
from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import SunshareDataUpdateCoordinator
from .entity import SunshareEntity

# Fallback max if a device hasn't reported countryMaxPower yet (matches the
# 800 W example in API_DOCUMENTATION.md for a German account).
DEFAULT_MAX_POWER = 800


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: SunshareDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        SunshareOutputPowerNumber(coordinator, device_id)
        for device_id in coordinator.data
    )


class SunshareOutputPowerNumber(SunshareEntity, NumberEntity):
    """Constant output wattage, 0..countryMaxPower — backed by updateEmsParaById.

    This is the confirmed control endpoint (API_DOCUMENTATION.md §6): writes
    here actually reach the physical inverter, unlike the generic
    sysDeviceInfo/updateById CRUD endpoint which only persists to the DB.
    """

    _attr_device_class = NumberDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_native_min_value = 0
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_translation_key = "output_power"

    def __init__(self, coordinator: SunshareDataUpdateCoordinator, device_id: int) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_output_power"

    @property
    def native_max_value(self) -> float:
        device = self.device
        if device and device.country_max_power:
            return float(device.country_max_power)
        return float(DEFAULT_MAX_POWER)

    @property
    def native_value(self) -> float | None:
        device = self.device
        if device is None or device.perm_power is None:
            return None
        return float(device.perm_power)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.client.async_set_output_power(self.device_id, int(value))
        await self.coordinator.async_request_refresh()
