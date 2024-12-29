"""Entity module."""

import logging
from typing import Dict, Optional, Set

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.entity import DeviceInfo, Entity, EntityCategory

from .const import DOMAIN
from .ewelink import XDevice, XRegistry

_LOGGER = logging.getLogger(__name__)

ENTITY_CATEGORIES: dict[str, EntityCategory] = {
    "battery": EntityCategory.DIAGNOSTIC,
    "battery_voltage": EntityCategory.DIAGNOSTIC,
    "led": EntityCategory.CONFIG,
    "pulse": EntityCategory.CONFIG,
    "pulseWidth": EntityCategory.CONFIG,
    "rssi": EntityCategory.DIAGNOSTIC,
    "sensitivity": EntityCategory.CONFIG,
}

ICONS: dict[str, str] = {
    "dusty": "mdi:cloud",
    "led": "mdi:led-off",
    "noise": "mdi:bell-ring",
}

NAMES: dict[str, str] = {
    "led": "LED",
    "rssi": "RSSI",
    "pulse": "INCHING",
    "pulseWidth": "INCHING Duration",
}


class XEntity(Entity):
    """Represents an eWeLink entity in Home Assistant."""

    event: bool = False  # If True, skips set_state on entity initialization
    params: Set[str] = set()
    param: Optional[str] = None
    uid: Optional[str] = None

    _attr_should_poll = False

    def __init__(self, ewelink: XRegistry, device: XDevice) -> None:
        """Initialize the eWeLink entity."""
        self.ewelink = ewelink
        self.device = device

        if self.param and not self.uid:
            self.uid = self.param
        if self.param and not self.params:
            self.params = {self.param}

        self._initialize_entity_attributes()

        deviceid: str = device["deviceid"]
        params: dict = device["params"]

        connections = (
            {(CONNECTION_NETWORK_MAC, params["staMac"])} if "staMac" in params else None
        )

        self._attr_device_info = DeviceInfo(
            connections=connections,
            identifiers={(DOMAIN, deviceid)},
            manufacturer=device.get("brandName"),
            model=device.get("productModel"),
            name=device["name"],
            sw_version=params.get("fwVersion"),
        )

        try:
            self.internal_update(None if self.event else params)
        except Exception as exc:
            _LOGGER.error("Cannot initialize device: %s", device, exc_info=exc)

        ewelink.dispatcher_connect(deviceid, self.internal_update)

        if parent := device.get("parent"):
            ewelink.dispatcher_connect(parent["deviceid"], self.internal_parent_update)

    def _initialize_entity_attributes(self) -> None:
        """Set up initial entity attributes."""
        if self.uid:
            self._attr_unique_id = f"{self.device['deviceid']}_{self.uid}"

            if not self.uid.isdigit():
                self._attr_entity_category = ENTITY_CATEGORIES.get(self.uid)
                self._attr_icon = ICONS.get(self.uid)

                name_suffix = NAMES.get(self.uid) or self.uid.title().replace("_", " ")
                self._attr_name = f"{self.device['name']} {name_suffix}"
            else:
                self._attr_name = self.device["name"]
        else:
            self._attr_name = self.device["name"]
            self._attr_unique_id = self.device["deviceid"]

        # Entity ID is auto-generated in Home Assistant
        self.entity_id = f"{DOMAIN}.{DOMAIN}_{self._attr_unique_id.lower()}"

    def set_state(self, params: Optional[dict]) -> None:
        """Set the state of the entity."""
        pass

    def internal_available(self) -> bool:
        """Check the availability of the device."""
        return self.ewelink.can_cloud(self.device) or self.ewelink.can_local(self.device)

    def internal_update(self, params: Optional[dict] = None) -> None:
        """Update the entity based on new parameters."""
        available = self.internal_available()
        change = False

        if self._attr_available != available:
            self._attr_available = available
            change = True

        if params and params.keys() & self.params:
            self.set_state(params)
            change = True

        if change and self.hass:
            self._async_write_ha_state()

    def internal_parent_update(self, params: Optional[dict] = None) -> None:
        """Handle updates from the parent device."""
        self.internal_update(None)

    async def async_update(self) -> None:
        """Request an update from the device."""
        if led := self.device["params"].get("sledOnline"):
            await self.ewelink.send(
                self.device, params_lan={"sledOnline": led}, cmd_lan="sledonline"
            )
        else:
            await self.ewelink.send(self.device)
