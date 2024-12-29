"""Fan module."""

from homeassistant.components.fan import (
    FanEntity,
    FanEntityFeature,
)
from homeassistant.const import MAJOR_VERSION, MINOR_VERSION

from .core.const import DOMAIN
from .core.entity import XEntity
from .core.ewelink import SIGNAL_ADD_ENTITIES, XRegistry, XDevice
from homeassistant.core import HomeAssistant
PARALLEL_UPDATES = 0  # Fix for entity platform parallel updates semaphore


async def async_setup_entry(hass:HomeAssistant, config_entry, add_entities):
    """Set up fan entities from a configuration entry."""
    ewelink: XRegistry = hass.data[DOMAIN][config_entry.entry_id]
    ewelink.dispatcher_connect(
        SIGNAL_ADD_ENTITIES,
        lambda x: add_entities([e for e in x if isinstance(e, FanEntity)]),
    )


# Speed modes for fans
SPEED_OFF = "off"
SPEED_LOW = "low"
SPEED_MEDIUM = "medium"
SPEED_HIGH = "high"
MODES = [SPEED_OFF, SPEED_LOW, SPEED_MEDIUM, SPEED_HIGH]


# noinspection PyAbstractClass
class XFan(XEntity, FanEntity):
    """Represents a standard fan entity for Home Assistant."""

    params = {"switches", "fan"}
    _attr_speed_count = 3

    # Feature support based on Home Assistant version
    if (MAJOR_VERSION, MINOR_VERSION) >= (2024, 8):
        _attr_supported_features = (
            FanEntityFeature.SET_SPEED
            | FanEntityFeature.TURN_OFF
            | FanEntityFeature.TURN_ON
        )
    else:
        _attr_supported_features = FanEntityFeature.SET_SPEED

    def __init__(self, ewelink: XRegistry, device: XDevice) -> None:
        """Initialize the XFan entity."""
        super().__init__(ewelink, device)

        if device.get("preset_mode", True):
            self._attr_preset_modes = MODES
            self._attr_supported_features |= FanEntityFeature.PRESET_MODE

    def set_state(self, params: dict):
        """Update the state of the fan based on provided parameters."""
        mode = None
        if "switches" in params:
            s = {i["outlet"]: i["switch"] for i in params["switches"]}
            if s[1] == "off":
                pass
            elif s[2] == "off" and s[3] == "off":
                mode = SPEED_LOW
            elif s[2] == "on" and s[3] == "off":
                mode = SPEED_MEDIUM
            elif s[2] == "off" and s[3] == "on":
                mode = SPEED_HIGH
        elif params["fan"] == "off":
            pass
        elif params["speed"] == 1:
            mode = SPEED_LOW
        elif params["speed"] == 2:
            mode = SPEED_MEDIUM
        elif params["speed"] == 3:
            mode = SPEED_HIGH

        self._attr_percentage = int(
            MODES.index(mode or SPEED_OFF) / self._attr_speed_count * 100
        )
        self._attr_preset_mode = mode

    async def async_set_percentage(self, percentage: int):
        """Set the speed percentage of the fan."""
        if percentage is None:
            param = {1: "on"}
            params_lan = {"fan": "on"}
        elif percentage > 66:
            param = {1: "on", 2: "off", 3: "on"}  # High
            params_lan = {"fan": "on", "speed": 3}
        elif percentage > 33:
            param = {1: "on", 2: "on", 3: "off"}  # Medium
            params_lan = {"fan": "on", "speed": 2}
        elif percentage > 0:
            param = {1: "on", 2: "off", 3: "off"}  # Low
            params_lan = {"fan": "on", "speed": 1}
        else:
            param = {1: "off"}
            params_lan = {"fan": "off"}
        param = [{"outlet": k, "switch": v} for k, v in param.items()]
        if self.device.get("localtype") != "fan_light":
            params_lan = None
        await self.ewelink.send(self.device, {"switches": param}, params_lan)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the fan to a specific preset mode."""
        percentage = int(
            self._attr_preset_modes.index(preset_mode) / self._attr_speed_count * 100
        )
        await self.async_set_percentage(percentage)

    async def async_turn_on(self, percentage=None, preset_mode=None, **kwargs):
        """Turn on the fan with optional speed or preset mode."""
        if preset_mode:
            await self.async_set_preset_mode(preset_mode)
        else:
            await self.async_set_percentage(percentage)

    async def async_turn_off(self):
        """Turn off the fan."""
        await self.async_set_percentage(0)


class XDiffuserFan(XFan):
    """Represents a diffuser fan entity."""

    params = {"state", "switch"}
    _attr_speed_count = 2
    _attr_preset_modes = [SPEED_OFF, SPEED_LOW, SPEED_HIGH]

    def set_state(self, params: dict):
        """Update the state of the diffuser fan."""
        if params["switch"] == "off":
            self._attr_percentage = 0
            self._attr_preset_mode = None
        elif params["state"] == 1:
            self._attr_percentage = 50
            self._attr_preset_mode = SPEED_LOW
        elif params["state"] == 2:
            self._attr_percentage = 100
            self._attr_preset_mode = SPEED_HIGH

    async def async_set_percentage(self, percentage: int):
        """Set the speed percentage of the diffuser fan."""
        if percentage is None:
            param = {"switch": "on"}
        elif percentage > 50:
            param = {"switch": "on", "state": 2}
        elif percentage > 0:
            param = {"switch": "on", "state": 1}
        else:
            param = {"switch": "off"}
        await self.ewelink.send(self.device, param)


class XFanDualR3(XFan):
    """Represents a fan entity for the DualR3 device."""

    params = {"motorTurn"}
    _attr_entity_registry_enabled_default = False
    _attr_speed_count = 2
    _attr_preset_modes = [SPEED_OFF, SPEED_LOW, SPEED_HIGH]

    def set_state(self, params: dict):
        """Update the state of the DualR3 fan."""
        if params["motorTurn"] == 0:
            self._attr_percentage = 0
            self._attr_preset_mode = None
        elif params["motorTurn"] == 1:
            self._attr_percentage = 50
            self._attr_preset_mode = SPEED_LOW
        elif params["motorTurn"] == 2:
            self._attr_percentage = 100
            self._attr_preset_mode = SPEED_HIGH

    async def async_set_percentage(self, percentage: int):
        """Set the speed percentage of the DualR3 fan."""
        if percentage is None:
            param = {"motorTurn": 0}
        elif percentage > 50:
            param = {"motorTurn": 2}
        elif percentage > 0:
            param = {"motorTurn": 1}
        else:
            param = {"motorTurn": 0}
        await self.ewelink.send(self.device, param)


class XToggleFan(XEntity, FanEntity):
    """Represents a simple toggle fan entity."""

    if (MAJOR_VERSION, MINOR_VERSION) >= (2024, 8):
        _attr_supported_features = FanEntityFeature.TURN_OFF | FanEntityFeature.TURN_ON

    @property
    def is_on(self):
        """Check if the fan is on."""
        return self._attr_is_on
