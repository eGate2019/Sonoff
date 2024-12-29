import asyncio

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.script import ATTR_LAST_TRIGGERED
from homeassistant.const import STATE_ON
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt

from .core.const import DOMAIN
from .core.entity import XEntity
from .core.ewelink import SIGNAL_ADD_ENTITIES, XRegistry

PARALLEL_UPDATES = 0  # fix entity_platform parallel_updates Semaphore

async def async_setup_entry(hass, config_entry, add_entities):
    """Set up the binary sensor entry for the integration."""
    ewelink: XRegistry = hass.data[DOMAIN][config_entry.entry_id]
    ewelink.dispatcher_connect(
        SIGNAL_ADD_ENTITIES,
        lambda x: add_entities([e for e in x if isinstance(e, BinarySensorEntity)]),
    )

# noinspection PyUnresolvedReferences
DEVICE_CLASSES = {cls.value: cls for cls in BinarySensorDeviceClass}

# noinspection PyAbstractClass
class XBinarySensor(XEntity, BinarySensorEntity):
    """Representation of a generic binary sensor."""
    default_class: str = None

    def __init__(self, ewelink: XRegistry, device: dict):
        """Initialize the binary sensor."""
        XEntity.__init__(self, ewelink, device)

        device_class = device.get("device_class", self.default_class)
        if device_class in DEVICE_CLASSES:
            self._attr_device_class = DEVICE_CLASSES[device_class]

    def set_state(self, params: dict):
        """Update the state of the binary sensor based on parameters."""
        self._attr_is_on = params[self.param] == 1

# noinspection PyAbstractClass
class XWiFiDoor(XBinarySensor):
    """Representation of a WiFi door sensor."""
    params = {"switch"}
    _attr_device_class = BinarySensorDeviceClass.DOOR

    def set_state(self, params: dict):
        """Update the state of the WiFi door sensor."""
        self._attr_is_on = params["switch"] == "on"

    def internal_available(self) -> bool:
        """Check the availability of the device, fixing buggy online status."""
        return self.ewelink.cloud.online

# noinspection PyAbstractClass
class XZigbeeMotion(XBinarySensor):
    """Representation of a Zigbee motion sensor."""
    params = {"motion", "online"}
    _attr_device_class = BinarySensorDeviceClass.MOTION

    def set_state(self, params: dict):
        """Update the state of the Zigbee motion sensor."""
        if "motion" in params:
            self._attr_is_on = params["motion"] == 1
        elif params.get("online") is False:
            # Fix stuck in `on` state after bridge goes to unavailable
            # https://github.com/AlexxIT/SonoffLAN/pull/425
            self._attr_is_on = False

class XHumanSensor(XEntity, BinarySensorEntity):
    """Representation of a human occupancy sensor."""
    param = "human"
    uid = "occupancy"
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    def set_state(self, params: dict):
        """Update the state of the human sensor."""
        self._attr_is_on = params[self.param] == 1

class XLightSensor(XEntity, BinarySensorEntity):
    """Representation of a light sensor."""
    param = "brState"
    uid = "light"
    _attr_device_class = BinarySensorDeviceClass.LIGHT

    def set_state(self, params: dict):
        """Update the state of the light sensor."""
        self._attr_is_on = params[self.param] == "brighter"

class XWaterSensor(XEntity, BinarySensorEntity):
    """Representation of a water moisture sensor."""
    param = "water"
    uid = "moisture"
    _attr_device_class = BinarySensorDeviceClass.MOISTURE

    def set_state(self, params: dict):
        """Update the state of the water sensor."""
        self._attr_is_on = params[self.param] == 1

# noinspection PyAbstractClass
class XRemoteSensor(BinarySensorEntity, RestoreEntity):
    """Representation of a remote sensor."""
    _attr_is_on = False
    task: asyncio.Task = None

    def __init__(self, ewelink: XRegistry, bridge: dict, child: dict):
        """Initialize the remote sensor."""
        self.ewelink = ewelink
        self.channel = child["channel"]
        self.timeout = child.get("timeout", 120)

        self._attr_device_class = DEVICE_CLASSES.get(child.get("device_class"))
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, bridge["deviceid"])})
        self._attr_extra_state_attributes = {}
        self._attr_name = child["name"]
        self._attr_unique_id = f"{bridge['deviceid']}_{self.channel}"

        self.entity_id = DOMAIN + "." + self._attr_unique_id

    def internal_update(self, ts: str):
        """Update the internal state of the sensor with a timestamp."""
        if self.task:
            self.task.cancel()

        self._attr_extra_state_attributes = {ATTR_LAST_TRIGGERED: ts}
        self._attr_is_on = True
        self._async_write_ha_state()

        if self.timeout:
            self.task = asyncio.create_task(self.clear_state(self.timeout))

    async def clear_state(self, delay: int):
        """Clear the state of the sensor after a delay."""
        await asyncio.sleep(delay)
        self._attr_is_on = False
        self._async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Handle addition of the sensor to Home Assistant."""
        # Restore previous sensor state
        # If sensor has timeout - restore remaining timer and check expired
        restore = await self.async_get_last_state()
        if not restore:
            return

        self._attr_is_on = restore.state == STATE_ON

        if (
            self.is_on
            and self.timeout
            and (ts := restore.attributes.get(ATTR_LAST_TRIGGERED))
        ):
            left = self.timeout - (dt.utcnow() - dt.parse_datetime(ts)).seconds
            if left > 0:
                self.task = asyncio.create_task(self.clear_state(left))
            else:
                self._attr_is_on = False

    async def async_will_remove_from_hass(self):
        """Handle removal of the sensor from Home Assistant."""
        if self.task:
            self.task.cancel()

class XRemoteSensorOff:
    """Representation of an auxiliary sensor to handle sensor-off state."""

    def __init__(self, child: dict, sensor: XRemoteSensor):
        """Initialize the auxiliary sensor-off handler."""
        self.channel = child["channel"]
        self.name = child["name"]
        self.sensor = sensor

    # noinspection PyProtectedMember
    def internal_update(self, ts: str):
        """Update the sensor to an off state using the provided timestamp."""
        self.sensor._attr_is_on = False
        self.sensor._async_write_ha_state()
        self.sensor._async_write_ha_state()
