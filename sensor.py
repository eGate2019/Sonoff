"""Sensor module."""
import asyncio
import time
from typing import Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .core.const import DOMAIN
from .core.entity import XEntity
from .core.ewelink import SIGNAL_ADD_ENTITIES, XRegistry

PARALLEL_UPDATES = 0  # fix entity_platform parallel_updates Semaphore


async def async_setup_entry(hass:HomeAssistant, config_entry, add_entities):
    """Set up entities from the config entry."""
    ewelink: XRegistry = hass.data[DOMAIN][config_entry.entry_id]
    ewelink.dispatcher_connect(
        SIGNAL_ADD_ENTITIES,
        lambda x: add_entities([e for e in x if isinstance(e, SensorEntity)]),
    )


DEVICE_CLASSES = {
    "battery": SensorDeviceClass.BATTERY,
    "battery_voltage": SensorDeviceClass.VOLTAGE,
    "current": SensorDeviceClass.CURRENT,
    "humidity": SensorDeviceClass.HUMIDITY,
    "outdoor_temp": SensorDeviceClass.TEMPERATURE,
    "power": SensorDeviceClass.POWER,
    "rssi": SensorDeviceClass.SIGNAL_STRENGTH,
    "temperature": SensorDeviceClass.TEMPERATURE,
    "voltage": SensorDeviceClass.VOLTAGE,
}

UNITS = {
    "battery": PERCENTAGE,
    "battery_voltage": UnitOfElectricPotential.VOLT,
    "current": UnitOfElectricCurrent.AMPERE,
    "humidity": PERCENTAGE,
    "outdoor_temp": UnitOfTemperature.CELSIUS,
    "power": UnitOfPower.WATT,
    "rssi": SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    "temperature": UnitOfTemperature.CELSIUS,
    "voltage": UnitOfElectricPotential.VOLT,
}


class XSensor(XEntity, SensorEntity):
    """Convert string sensor values, apply reporting logic, and update states."""

    multiply: float = None
    round: int = None

    report_ts = None
    report_mint = None
    report_maxt = None
    report_delta = None
    report_value = None

    def __init__(self, ewelink: XRegistry, device: dict)->None:
        """Initialize the sensor with device data."""
        if self.param and self.uid is None:
            self.uid = self.param

        # remove tailing _1 _2 _3 _4
        default_class = self.uid.rstrip("_01234")

        if device["params"].get(self.param) in ("on", "off"):
            default_class = None

        if device_class := DEVICE_CLASSES.get(default_class):
            self._attr_device_class = device_class

        if default_class in UNITS:
            # by default all sensors with units are measurement sensors
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_native_unit_of_measurement = UNITS[default_class]

        XEntity.__init__(self, ewelink, device)

        reporting = device.get("reporting", {}).get(self.uid)
        if reporting:
            self.report_mint, self.report_maxt, self.report_delta = reporting
            self.report_ts = time.time()
            self._attr_should_poll = True

    def set_state(self, params: dict = None, value: float = None):
        """Set the sensor state and apply filtering logic."""
        if params:
            value = params[self.param]
            if self.native_unit_of_measurement and isinstance(value, str):
                try:
                    value = float(value)
                except Exception:
                    return
            if self.multiply:
                value *= self.multiply
            if self.round is not None:
                value = round(value, self.round or None)

        if self.report_ts is not None:
            ts = time.time()

            try:
                if (ts - self.report_ts < self.report_mint) or (
                    ts - self.report_ts < self.report_maxt
                    and abs(value - self.native_value) <= self.report_delta
                ):
                    self.report_value = value
                    return

                self.report_value = None
            except Exception:
                pass

            self.report_ts = ts

        self._attr_native_value = value

    async def async_update(self):
        """Update the sensor state asynchronously."""
        if self.report_value is not None:
            XSensor.set_state(self, value=self.report_value)


class XTemperatureTH(XSensor):
    """Handle temperature sensor state with filtering for invalid values."""

    params = {"currentTemperature", "temperature"}
    uid = "temperature"

    def set_state(self, params: dict = None, value: float = None):
        """Set the temperature sensor state with validation."""
        try:
            value = params.get("currentTemperature") or params["temperature"]
            value = float(value)
            if value != 0 and -270 < value < 270:
                XSensor.set_state(self, value=round(value, 1))
        except Exception:
            XSensor.set_state(self)


class XHumidityTH(XSensor):
    """Handle humidity sensor state with filtering for invalid values."""

    params = {"currentHumidity", "humidity"}
    uid = "humidity"

    def set_state(self, params: dict = None, value: float = None):
        """Set the humidity sensor state with validation."""
        try:
            value = params.get("currentHumidity") or params["humidity"]
            value = float(value)
            if value != 0:
                XSensor.set_state(self, value=value)
        except Exception:
            XSensor.set_state(self)


class XEnergySensor(XEntity, SensorEntity):
    """Handle energy sensor state and manage historical data."""

    get_params = None
    next_ts = 0

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_entity_registry_enabled_default = False
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_should_poll = True

    def __init__(self, ewelink: XRegistry, device: dict)->None:
        """Initialize the energy sensor with device data."""
        XEntity.__init__(self, ewelink, device)
        reporting = device.get("reporting", {})
        self.report_dt, self.report_history = reporting.get(self.uid) or (3600, 0)

    @staticmethod
    def decode_energy(value: str) -> Optional[list]:
        """Decode the energy value from a string."""
        try:
            return [
                round(
                    int(value[i : i + 2], 16)
                    + int(value[i + 3], 10) * 0.1
                    + int(value[i + 5], 10) * 0.01,
                    2,
                )
                for i in range(0, len(value), 6)
            ]
        except Exception:
            return None

    def set_state(self, params: dict):
        """Set the energy sensor state with decoded history."""
        history = self.decode_energy(params[self.param])
        if not history:
            return

        self._attr_native_value = history[0]

        if self.report_history:
            self._attr_extra_state_attributes = {
                "history": history[0 : self.report_history]
            }

    async def async_update(self):
        """Update the energy sensor state asynchronously."""
        ts = time.time()
        if ts < self.next_ts or not self.available or not self.ewelink.cloud.online:
            return
        ok = await self.ewelink.send_cloud(self.device, self.get_params, query=False)
        if ok == "online":
            self.next_ts = ts + self.report_dt


class XEnergySensorDualR3(XEnergySensor, SensorEntity):
    """Handle energy sensor state for dual-channel R3 sensor."""

    @staticmethod
    def decode_energy(value: str) -> Optional[list]:
        """Decode the energy value for dual-channel R3 sensor."""
        try:
            return [
                round(
                    int(value[i : i + 2], 16) + int(value[i + 2 : i + 4], 10) * 0.01, 2
                )
                for i in range(0, len(value), 4)
            ]
        except Exception:
            return None


class XEnergySensorPOWR3(XEnergySensor, SensorEntity):
    """Handle energy sensor state for POWR3 sensor."""

    @staticmethod
    def decode_energy(value: str) -> Optional[list]:
        """Decode the energy value for POWR3 sensor."""
        try:
            return [
                round(int(value[i], 16) + int(value[i + 1 : i + 3], 10) * 0.01, 2)
                for i in range(0, len(value), 3)
            ]
        except Exception:
            return None

    async def async_update(self):
        """Update the POWR3 energy sensor state asynchronously."""
        ts = time.time()
        if ts < self.next_ts or not self.available:
            return
        ok = await self.ewelink.send(self.device, self.get_params, timeout_lan=5)
        if ok == "online":
            self.next_ts = ts + self.report_dt


class XEnergyTotal(XSensor):
    """Handle total energy sensor state."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL


class XTemperatureNS(XSensor):
    """Handle temperature sensor with corrections."""

    params = {"temperature", "tempCorrection"}
    uid = "temperature"

    def set_state(self, params: dict = None, value: float = None):
        """Set the temperature state with correction."""
        if params:
            cache = self.device["params"]
            value = cache["temperature"] + cache.get("tempCorrection", 0)
        XSensor.set_state(self, value=value)


class XOutdoorTempNS(XSensor):
    """Handle outdoor temperature sensor state."""

    param = "HMI_outdoorTemp"
    uid = "outdoor_temp"

    def set_state(self, params: dict):
        """Set the outdoor temperature sensor state."""
        try:
            value = params[self.param]
            self._attr_native_value = value["current"]

            mint, maxt = value["range"].split(",")
            self._attr_extra_state_attributes = {
                "temp_min": int(mint),
                "temp_max": int(maxt),
            }
        except Exception:
            pass


class XWiFiDoorBattery(XSensor):
    """Handle Wi-Fi door battery sensor state."""

    param = "battery"
    uid = "battery_voltage"

    def internal_available(self) -> bool:
        """Check if the device is available."""
        return self.ewelink.cloud.online


BUTTON_STATES = ["single", "double", "hold"]


class XEventSesor(XEntity, SensorEntity):
    """Handle event sensor states."""

    event = True
    _attr_native_value = ""

    async def clear_state(self):
        """Clear the event sensor state."""
        await asyncio.sleep(0.5)
        self._attr_native_value = ""
        if self.hass:
            self._async_write_ha_state()


class XRemoteButton(XEventSesor):
    """Handle remote button event sensor states."""

    params = {"key"}

    def set_state(self, params: dict):
        """Set the remote button state."""
        button = params.get("outlet")
        key = BUTTON_STATES[params["key"]]
        self._attr_native_value = (
            f"button_{button + 1}_{key}" if button is not None else key
        )
        asyncio.create_task(self.clear_state())  # noqa: RUF006


class XT5Action(XEventSesor):
    """Handle XT5 action event sensor states."""

    params = {"triggerType", "slide"}
    uid = "action"

    def set_state(self, params: dict):
        """Set the XT5 action state."""
        if "switches" in params and params.get("triggerType") == 2:
            self._attr_native_value = "touch"
            asyncio.create_task(self.clear_state())  # noqa: RUF006

        if (slide := params.get("slide")) and len(params) == 1:
            self._attr_native_value = f"slide_{slide}"
            asyncio.create_task(self.clear_state())  # noqa: RUF006


class XUnknown(XEntity, SensorEntity):
    """Handle unknown sensor states."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def internal_update(self, params: dict = None):
        """Update the unknown sensor state."""
        self._attr_native_value = dt_util.utcnow()

        if params is not None:
            params.pop("bindInfos", None)
            self._attr_extra_state_attributes = params

        if self.hass:
            self._async_write_ha_state()
