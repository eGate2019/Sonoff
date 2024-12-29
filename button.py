from homeassistant.components.button import ButtonEntity
from homeassistant.components.script import ATTR_LAST_TRIGGERED
from homeassistant.helpers.entity import DeviceInfo

from .core.const import DOMAIN
from .core.ewelink import SIGNAL_ADD_ENTITIES, XRegistry

PARALLEL_UPDATES = 0  # fix entity_platform parallel_updates Semaphore

async def async_setup_entry(hass, config_entry, add_entities):
    """Set up the button entities for the eWeLink integration."""
    ewelink: XRegistry = hass.data[DOMAIN][config_entry.entry_id]
    ewelink.dispatcher_connect(
        SIGNAL_ADD_ENTITIES,
        lambda x: add_entities([e for e in x if isinstance(e, ButtonEntity)]),
    )

class XRemoteButton(ButtonEntity):
    """Representation of a remote-controlled button for eWeLink devices."""

    def __init__(self, ewelink: XRegistry, bridge: dict, child: dict):
        """Initialize the button entity.

        :param ewelink: The eWeLink registry instance.
        :param bridge: The parent bridge device information.
        :param child: The child button details.
        """
        self.ewelink = ewelink
        self.bridge = bridge
        self.channel = child["channel"]

        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, bridge["deviceid"])})
        self._attr_extra_state_attributes = {}
        self._attr_name = child["name"]
        self._attr_unique_id = f"{bridge['deviceid']}_{self.channel}"

        self.entity_id = DOMAIN + "." + self._attr_unique_id

    def internal_update(self, ts: str):
        """Update the state attributes of the button entity.

        :param ts: Timestamp of the last triggered action.
        """
        self._attr_extra_state_attributes = {ATTR_LAST_TRIGGERED: ts}
        self._async_write_ha_state()

    async def async_press(self):
        """Handle the button press action."""
        await self.ewelink.send(
            self.bridge,
            {"cmd": "transmit", "rfChl": int(self.channel)},
            cmd_lan="transmit",
        )
