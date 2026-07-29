"""Shared base entity for the Sunshare integration."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import SunshareDataUpdateCoordinator, SunshareDevice


class SunshareEntity(CoordinatorEntity[SunshareDataUpdateCoordinator]):
    """Base entity tying a Sunshare device id to coordinator data + device_info."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SunshareDataUpdateCoordinator, device_id: int) -> None:
        super().__init__(coordinator)
        self.device_id = device_id

    @property
    def device(self) -> SunshareDevice | None:
        return self.coordinator.data.get(self.device_id)

    @property
    def device_info(self) -> DeviceInfo:
        device = self.device
        return DeviceInfo(
            identifiers={(DOMAIN, str(self.device_id))},
            name=device.name if device else None,
            manufacturer=MANUFACTURER,
            model=device.model if device else None,
            sw_version=device.ota_ver if device else None,
            serial_number=device.sn if device else None,
        )
