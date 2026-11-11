"""Base entity of the EDF regulated tariffs (TRVE) integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TrveEdfCoordinator


class TrveEdfEntity(CoordinatorEntity[TrveEdfCoordinator]):
    """Entity of a TRVE contract, attached to the device of the contract."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TrveEdfCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            entry_type=DeviceEntryType.SERVICE,
        )
