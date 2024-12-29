"""Switch module."""
from homeassistant.components.switch import SwitchEntity

from .core.const import DOMAIN
from .core.entity import XEntity
from .core.ewelink import SIGNAL_ADD_ENTITIES, XRegistry

PARALLEL_UPDATES = 0  # fix entity_platform parallel_updates Semaphore
from homeassistant.core import HomeAssistant
import contextlib

async def async_setup_entry(hass: HomeAssistant, config_entry, add_entities):
    """Set up the switch entities."""
    ewelink: XRegistry = hass.data[DOMAIN][config_entry.entry_id]
    ewelink.dispatcher_connect(
        SIGNAL_ADD_ENTITIES,
        lambda x: add_entities([e for e in x if isinstance(e, SwitchEntity)]),
    )


class XSwitch(XEntity, SwitchEntity):
    """Handle the state of a single switch."""

    params = {"switch"}

    def set_state(self, params: dict):
        """Set the state of the switch."""
        self._attr_is_on = params["switch"] == "on"

    async def async_turn_on(self, *args, **kwargs):
        """Turn the switch on."""
        await self.ewelink.send(self.device, {"switch": "on"})

    async def async_turn_off(self):
        """Turn the switch off."""
        await self.ewelink.send(self.device, {"switch": "off"})


class XSwitches(XEntity, SwitchEntity):
    """Handle the state of multiple switches."""

    params = {"switches"}
    channel: int = 0

    def __init__(self, ewelink: XRegistry, device: dict)->None:
        """Initialize the switch entity."""
        XEntity.__init__(self, ewelink, device)

        with contextlib.suppress(KeyError):
            self._attr_name = device["tags"]["ck_channel_name"][str(self.channel)]
        # backward compatibility
        self._attr_unique_id = f"{device['deviceid']}_{self.channel + 1}"

    def set_state(self, params: dict):
        """Set the state of the switch."""
        try:
            params = next(i for i in params["switches"] if i["outlet"] == self.channel)
            self._attr_is_on = params["switch"] == "on"
        except StopIteration:
            pass

    async def async_turn_on(self, *args, **kwargs):
        """Turn the switch on."""
        params = {"switches": [{"outlet": self.channel, "switch": "on"}]}
        await self.ewelink.send_bulk(self.device, params)

    async def async_turn_off(self):
        """Turn the switch off."""
        params = {"switches": [{"outlet": self.channel, "switch": "off"}]}
        await self.ewelink.send_bulk(self.device, params)


class XSwitchTH(XSwitch):
    """Handle the state of a switch with a main switch."""

    async def async_turn_on(self):
        """Turn the switch on along with the main switch."""
        params = {"switch": "on", "mainSwitch": "on", "deviceType": "normal"}
        await self.ewelink.send(self.device, params)

    async def async_turn_off(self):
        """Turn the switch off along with the main switch."""
        params = {"switch": "off", "mainSwitch": "off", "deviceType": "normal"}
        await self.ewelink.send(self.device, params)


class XSwitchPOWR3(XSwitches):
    """Handle the state of a POWR3 switch."""

    async def async_turn_on(self):
        """Turn the POWR3 switch on."""
        params = {"switches": [{"outlet": 0, "switch": "on"}], "operSide": 1}
        await self.ewelink.send(self.device, params)

    async def async_turn_off(self):
        """Turn the POWR3 switch off."""
        params = {"switches": [{"outlet": 0, "switch": "off"}], "operSide": 1}
        await self.ewelink.send(self.device, params)


class XZigbeeSwitches(XSwitches):
    """Handle Zigbee switches, which send all channels at once."""

    async def async_turn_on(self, **kwargs):
        """Turn all Zigbee switch channels on."""
        switches = [
            {"outlet": self.channel, "switch": "on"}
            if switch["outlet"] == self.channel
            else switch
            for switch in self.device["params"]["switches"]
        ]
        await self.ewelink.send(self.device, {"switches": switches})

    async def async_turn_off(self):
        """Turn all Zigbee switch channels off."""
        switches = [
            {"outlet": self.channel, "switch": "off"}
            if switch["outlet"] == self.channel
            else switch
            for switch in self.device["params"]["switches"]
        ]
        await self.ewelink.send(self.device, {"switches": switches})


class XToggle(XEntity, SwitchEntity):
    """Handle toggle switch states."""

    def set_state(self, params: dict):
        """Set the state of the toggle switch."""
        self.device["params"][self.param] = params[self.param]
        self._attr_is_on = params[self.param] == "on"

    async def async_turn_on(self):
        """Turn the toggle switch on."""
        await self.ewelink.send(self.device, {self.param: "on"})

    async def async_turn_off(self):
        """Turn the toggle switch off."""
        await self.ewelink.send(self.device, {self.param: "off"})


class XDetach(XEntity, SwitchEntity):
    """Handle relay separation for switches."""

    param = "relaySeparation"
    uid = "detach"

    _attr_entity_registry_enabled_default = False

    def set_state(self, params: dict):
        """Set the state of the detach switch."""
        self._attr_is_on = params["relaySeparation"] == 1

    async def async_turn_on(self, **kwargs):
        """Turn the detach relay on."""
        await self.ewelink.send_cloud(self.device, {"relaySeparation": 1})

    async def async_turn_off(self):
        """Turn the detach relay off."""
        await self.ewelink.send_cloud(self.device, {"relaySeparation": 0})


class XBoolSwitch(XEntity, SwitchEntity):
    """Handle a boolean switch."""

    params = {"switch"}

    def set_state(self, params: dict):
        """Set the state of the boolean switch."""
        self._attr_is_on = params["switch"]

    async def async_turn_on(self, *args, **kwargs):
        """Turn the boolean switch on."""
        await self.ewelink.send(self.device, {"switch": True})

    async def async_turn_off(self):
        """Turn the boolean switch off."""
        await self.ewelink.send(self.device, {"switch": False})
