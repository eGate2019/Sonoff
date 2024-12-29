from homeassistant.components.cover import CoverDeviceClass, CoverEntity

from .core.const import DOMAIN
from .core.entity import XEntity
from .core.ewelink import SIGNAL_ADD_ENTITIES, XRegistry

PARALLEL_UPDATES = 0  # Fix entity_platform parallel_updates Semaphore


async def async_setup_entry(hass, config_entry, add_entities):
    """Set up the eWeLink cover entities from a config entry."""
    ewelink: XRegistry = hass.data[DOMAIN][config_entry.entry_id]
    ewelink.dispatcher_connect(
        SIGNAL_ADD_ENTITIES,
        lambda x: add_entities([e for e in x if isinstance(e, CoverEntity)]),
    )


# Mapping of device classes for cover entities
DEVICE_CLASSES = {cls.value: cls for cls in CoverDeviceClass}


class XCover(XEntity, CoverEntity):
    """Representation of a cover entity."""

    params = {"switch", "setclose"}

    def __init__(self, ewelink: XRegistry, device: dict):
        """Initialize the cover entity."""
        super().__init__(ewelink, device)
        self._attr_device_class = DEVICE_CLASSES.get(device.get("device_class"))

    def set_state(self, params: dict):
        """Update the state of the cover based on received parameters."""
        if len(params) == 1:
            if "switch" in params:
                # Interpret switch command: on=open, off=close
                self._attr_is_opening = params["switch"] == "on"
                self._attr_is_closing = params["switch"] == "off"
            elif "setclose" in params:
                # Update state based on position
                pos = 100 - params["setclose"]
                self._attr_is_closing = pos < self.current_cover_position
                self._attr_is_opening = pos > self.current_cover_position

        elif "setclose" in params:
            # Device has finished an action; update position accordingly
            self._attr_current_cover_position = 100 - params["setclose"]
            self._attr_is_closed = self.current_cover_position == 0
            self._attr_is_closing = False
            self._attr_is_opening = False

    async def async_stop_cover(self, **kwargs):
        """Stop the cover movement."""
        params = {"switch": "pause"}
        self.set_state(params)
        self._async_write_ha_state()
        await self.ewelink.send(self.device, params, query_cloud=False)

    async def async_open_cover(self, **kwargs):
        """Open the cover."""
        params = {"switch": "on"}
        self.set_state(params)
        self._async_write_ha_state()
        await self.ewelink.send(self.device, params, query_cloud=False)

    async def async_close_cover(self, **kwargs):
        """Close the cover."""
        params = {"switch": "off"}
        self.set_state(params)
        self._async_write_ha_state()
        await self.ewelink.send(self.device, params, query_cloud=False)

    async def async_set_cover_position(self, position: int, **kwargs):
        """Set the cover to a specific position."""
        params = {"setclose": 100 - position}
        self.set_state(params)
        self._async_write_ha_state()
        await self.ewelink.send(self.device, params, query_cloud=False)


class XCoverDualR3(XCover):
    """Representation of a dual motor cover entity."""

    params = {"currLocation", "motorTurn"}

    def set_state(self, params: dict):
        """Update the state of the dual motor cover based on parameters."""
        if "currLocation" in params:
            # Update current position (0 - closed, 100 - opened)
            self._attr_current_cover_position = params["currLocation"]
            self._attr_is_closed = self._attr_current_cover_position == 0

        if "motorTurn" in params:
            # Determine opening/closing state based on motor status
            if params["motorTurn"] == 0:  # stop
                self._attr_is_opening = False
                self._attr_is_closing = False
            elif params["motorTurn"] == 1:  # opening
                self._attr_is_opening = True
                self._attr_is_closing = False
            elif params["motorTurn"] == 2:  # closing
                self._attr_is_opening = False
                self._attr_is_closing = True

    async def async_stop_cover(self, **kwargs):
        """Stop the dual motor cover movement."""
        await self.ewelink.send(self.device, {"motorTurn": 0})

    async def async_open_cover(self, **kwargs):
        """Open the dual motor cover."""
        await self.ewelink.send(self.device, {"motorTurn": 1})

    async def async_close_cover(self, **kwargs):
        """Close the dual motor cover."""
        await self.ewelink.send(self.device, {"motorTurn": 2})

    async def async_set_cover_position(self, position: int, **kwargs):
        """Set the dual motor cover to a specific position."""
        await self.ewelink.send(self.device, {"location": position})


class XZigbeeCover(XCover):
    """Representation of a Zigbee cover entity."""

    params = {"curPercent", "curtainAction"}

    def set_state(self, params: dict):
        """Update the state of the Zigbee cover based on parameters."""
        if "curPercent" in params:
            # Update current position (0 - closed, 100 - opened)
            self._attr_current_cover_position = 100 - params["curPercent"]
            self._attr_is_closed = self._attr_current_cover_position == 0

    async def async_stop_cover(self, **kwargs):
        """Stop the Zigbee cover movement."""
        await self.ewelink.send(self.device, {"curtainAction": "pause"})

    async def async_open_cover(self, **kwargs):
        """Open the Zigbee cover."""
        await self.ewelink.send(self.device, {"curtainAction": "open"})

    async def async_close_cover(self, **kwargs):
        """Close the Zigbee cover."""
        await self.ewelink.send(self.device, {"curtainAction": "close"})

    async def async_set_cover_position(self, position: int, **kwargs):
        """Set the Zigbee cover to a specific position."""
        await self.ewelink.send(self.device, {"openPercent": 100 - position})


class XCover91(XEntity, CoverEntity):
    """Representation of a specific type of cover entity (XCover91)."""

    param = "op"

    _attr_is_closed = None  # Unknown initial state

    def set_state(self, params: dict):
        """Update the state of the XCover91 based on parameters."""
        if v := params.get(self.param):
            if v == 1:
                # Opening command received
                self._attr_is_opening = True
                self._attr_is_closing = False
            elif v == 2:
                # Stop command received
                self._attr_is_opening = False
                self._attr_is_closing = False
            elif v == 3:
                # Closing command received
                self._attr_is_opening = False
                self._attr_is_closing = True

    async def async_stop_cover(self, **kwargs):
        """Stop the XCover91 movement."""
        await self.ewelink.send(self.device, {self.param: 2})

    async def async_open_cover(self, **kwargs):
        """Open the XCover91."""
        await self.ewelink.send(self.device, {self.param: 1})

    async def async_close_cover(self, **kwargs):
        """Close the XCover91."""
        await self.ewelink.send(self.device, {self.param: 3})
