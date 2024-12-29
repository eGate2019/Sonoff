"""Number modules."""
from homeassistant.components.number import NumberEntity
from homeassistant.core import HomeAssistant

from .core.const import DOMAIN
from .core.entity import XEntity
from .core.ewelink import SIGNAL_ADD_ENTITIES, XRegistry

PARALLEL_UPDATES = 0  # fix entity_platform parallel_updates Semaphore


async def async_setup_entry(hass:HomeAssistant, config_entry, add_entities):
    """Set up the number entities for the given config entry."""
    ewelink: XRegistry = hass.data[DOMAIN][config_entry.entry_id]
    ewelink.dispatcher_connect(
        SIGNAL_ADD_ENTITIES,
        lambda x: add_entities([e for e in x if isinstance(e, NumberEntity)]),
    )


# noinspection PyAbstractClass
class XNumber(XEntity, NumberEntity):
    """Represent a number entity with multiplication and rounding support."""

    multiply: float = None
    round: int = None

    def set_state(self, params: dict):
        """Set the state of the number entity based on the provided parameters."""
        value = params[self.param]
        if self.multiply:
            value *= self.multiply
        if self.round is not None:
            value = round(value, self.round or None)
        self._attr_native_value = value

    async def async_set_native_value(self, value: float) -> None:
        """Set the native value of the number entity."""
        if self.multiply:
            value /= self.multiply
        await self.ewelink.send(self.device, {self.param: int(value)})


class XPulseWidth(XNumber):
    """Represent a pulse width number entity with specific pulse width settings."""

    param = "pulseWidth"

    _attr_entity_registry_enabled_default = False

    _attr_native_max_value = 36000
    _attr_native_min_value = 0.5
    _attr_native_step = 0.5

    def set_state(self, params: dict):
        """Set the pulse width state based on the provided parameters."""
        self._attr_native_value = params["pulseWidth"] / 1000

    async def async_set_native_value(self, value: float) -> None:
        """Set the native value of the pulse width, ensuring correct milliseconds format."""
        await self.ewelink.send(
            self.device, {"pulse": "on", "pulseWidth": int(value / 0.5) * 500}
        )


class XSensitivity(XNumber):
    """Represent a sensitivity number entity with specific sensitivity range."""

    param = "sensitivity"

    _attr_entity_registry_enabled_default = False
    _attr_native_max_value = 3
    _attr_native_min_value = 1

