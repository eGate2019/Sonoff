from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import ClimateEntityFeature, HVACMode
from homeassistant.const import MAJOR_VERSION, MINOR_VERSION, UnitOfTemperature
from homeassistant.core import HomeAssistant

from .core.const import DOMAIN
from .core.entity import XEntity
from .core.ewelink import SIGNAL_ADD_ENTITIES, XRegistry

PARALLEL_UPDATES = 0  # fix entity_platform parallel_updates Semaphore


async def async_setup_entry(hass:HomeAssistant, config_entry, add_entities):
    """Set up the entry for climate entities."""

    ewelink: XRegistry = hass.data[DOMAIN][config_entry.entry_id]
    ewelink.dispatcher_connect(
        SIGNAL_ADD_ENTITIES,
        lambda x: add_entities([e for e in x if isinstance(e, ClimateEntity)]),
    )


class XClimateTH(XEntity, ClimateEntity):
    """Represent a climate entity for temperature and humidity control."""

    params = {"targets", "deviceType", "currentTemperature", "temperature"}

    _attr_entity_registry_enabled_default = False
    _attr_hvac_mode = None
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.DRY]
    _attr_max_temp = 99
    _attr_min_temp = -40
    _attr_target_temperature_high = None
    _attr_target_temperature_low = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1

    if (MAJOR_VERSION, MINOR_VERSION) >= (2024, 2):
        _attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.SWING_MODE
        )
        _enable_turn_on_off_backwards_compatibility = False
    else:
        _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE_RANGE

    heat: bool = None

    def set_state(self, params: dict):
        """Update the state of the entity based on parameters from the device."""

        if "targets" in params:
            hi, lo = params["targets"]

            self._attr_is_aux_heat = lo["reaction"]["switch"] == "on"
            self._attr_target_temperature_high = float(hi["targetHigh"])
            self._attr_target_temperature_low = float(lo["targetLow"])

            if params["deviceType"] == "normal":
                self._attr_hvac_mode = HVACMode.OFF
            elif params["deviceType"] == "humidity":
                self._attr_hvac_mode = HVACMode.DRY
            elif self.is_aux_heat:
                self._attr_hvac_mode = HVACMode.HEAT
            else:
                self._attr_hvac_mode = HVACMode.COOL

        try:
            if self.hvac_mode != HVACMode.DRY:
                value = float(params.get("currentTemperature") or params["temperature"])
                value = round(value, 1)
            else:
                value = int(params.get("currentHumidity") or params["humidity"])
            self._attr_current_temperature = value
        except Exception:
            pass

    def get_targets(self, heat: bool) -> list:
        """Generate target temperature parameters for the device."""
        return [
            {
                "targetHigh": str(self.target_temperature_high),
                "reaction": {"switch": "off" if heat else "on"},
            },
            {
                "targetLow": str(self.target_temperature_low),
                "reaction": {"switch": "on" if heat else "off"},
            },
        ]

    async def async_set_hvac_mode(self, hvac_mode: str) -> None:
        """Set the HVAC mode for the device."""
        if hvac_mode == HVACMode.HEAT:
            params = {
                "mainSwitch": "on",
                "deviceType": "temperature",
                "targets": self.get_targets(True),
            }
        elif hvac_mode == HVACMode.COOL:
            params = {
                "mainSwitch": "on",
                "deviceType": "temperature",
                "targets": self.get_targets(False),
            }
        elif hvac_mode == HVACMode.DRY:
            params = {
                "mainSwitch": "on",
                "deviceType": "humidity",
                "targets": self.get_targets(self.is_aux_heat),
            }
        else:
            params = {"mainSwitch": "off", "deviceType": "normal"}
        await self.ewelink.send_cloud(self.device, params)

    async def async_set_temperature(
        self,
        hvac_mode: str = None,
        target_temp_high: float = None,
        target_temp_low: float = None,
        **kwargs
    ) -> None:
        """Set the target temperature for the device."""

        heat = self.is_aux_heat
        if hvac_mode is None:
            params = {}
        elif hvac_mode == HVACMode.HEAT:
            heat = True
            params = {"mainSwitch": "on", "deviceType": "temperature"}
        elif hvac_mode == HVACMode.COOL:
            heat = False
            params = {"mainSwitch": "on", "deviceType": "temperature"}
        elif hvac_mode == HVACMode.DRY:
            params = {"mainSwitch": "on", "deviceType": "humidity"}
        else:
            params = {"mainSwitch": "off", "deviceType": "normal"}

        if target_temp_high is not None and target_temp_low is not None:
            params["targets"] = [
                {
                    "targetHigh": str(target_temp_high),
                    "reaction": {"switch": "off" if heat else "on"},
                },
                {
                    "targetLow": str(target_temp_low),
                    "reaction": {"switch": "on" if heat else "off"},
                },
            ]

        await self.ewelink.send_cloud(self.device, params)

# noinspection PyAbstractClass
class XThermostat(XEntity, ClimateEntity):
    """Represent a thermostat entity within the Home Assistant ecosystem, capable of controlling and monitoring temperature."""

    params = {"switch", "targetTemp", "temperature", "workMode", "workState"}

    # Supported HVAC modes and attributes
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.AUTO]
    _attr_max_temp = 45
    _attr_min_temp = 5
    _attr_preset_modes = ["manual", "programmed", "economical"]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5

    # Feature support based on Home Assistant version
    if (MAJOR_VERSION, MINOR_VERSION) >= (2024, 2):
        _attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.PRESET_MODE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.SWING_MODE
        )
        _enable_turn_on_off_backwards_compatibility = False
    else:
        _attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        )

    def set_state(self, params: dict):
        """Update the state of the thermostat based on the provided parameters."""

        cache = self.device["params"]
        if cache != params:
            cache.update(params)

        if cache["switch"] == "on":
            # workState: 1=heating, 2=auto
            self._attr_hvac_mode = self.hvac_modes[cache["workState"]]
        else:
            self._attr_hvac_mode = HVACMode.OFF

        if "workMode" in params:
            self._attr_preset_mode = self.preset_modes[params["workMode"] - 1]

        if "targetTemp" in params:
            self._attr_target_temperature = params["targetTemp"]
        if "temperature" in params:
            self._attr_current_temperature = params["temperature"]

    async def async_set_hvac_mode(self, hvac_mode: str) -> None:
        """Set the HVAC mode for the thermostat."""

        i = self.hvac_modes.index(hvac_mode)
        params = {"switch": "on", "workState": i} if i else {"switch": "off"}
        await self.ewelink.send(self.device, params)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode for the thermostat."""

        i = self.preset_modes.index(preset_mode) + 1
        await self.ewelink.send(self.device, {"workMode": i})

    async def async_set_temperature(
        self,
        temperature: float = None,
        hvac_mode: str = None,
        preset_mode: str = None,
        **kwargs
    ) -> None:
        """Set the target temperature, HVAC mode, or preset mode for the thermostat."""

        if hvac_mode is None:
            params = {}
        elif hvac_mode is HVACMode.OFF:
            params = {"switch": "off"}
        else:
            i = self.hvac_modes.index(hvac_mode)
            params = {"switch": "on", "workState": i}

        if preset_mode is not None:
            params["workMode"] = self.preset_modes.index(preset_mode) + 1

        if temperature is not None:
            params["targetTemp"] = temperature

        await self.ewelink.send(self.device, params)
