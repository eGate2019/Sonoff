"""Light module."""

import time

from homeassistant.components.light import ColorMode, LightEntity, LightEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.util import color

from .core.const import DOMAIN
from .core.entity import XEntity
from .core.ewelink import SIGNAL_ADD_ENTITIES, XRegistry

PARALLEL_UPDATES = 0  # fix entity_platform parallel_updates Semaphore


async def async_setup_entry(hass:HomeAssistant, config_entry, add_entities):
    """Set up light entities from a configuration entry."""
    ewelink: XRegistry = hass.data[DOMAIN][config_entry.entry_id]
    ewelink.dispatcher_connect(
        SIGNAL_ADD_ENTITIES,
        lambda x: add_entities([e for e in x if isinstance(e, LightEntity)]),
    )


def conv(value: int, a1: int, a2: int, b1: int, b2: int) -> int:
    """Convert a value from one range to another."""
    value = round((value - a1) / (a2 - a1) * (b2 - b1) + b1)
    if value < min(b1, b2):
        value = min(b1, b2)
    if value > max(b1, b2):
        value = max(b1, b2)
    return value


###############################################################################
# Category 1. XLight base (brightness)
###############################################################################


class XOnOffLight(XEntity, LightEntity):
    """Represent a simple on/off light entity."""

    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}


# https://developers.home-assistant.io/docs/core/entity/light/
# noinspection PyAbstractClass
class XLight(XEntity, LightEntity):
    """Represent a dimmable light entity."""

    uid = ""  # prevent add param to entity_id

    # support on/off and brightness
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_supported_features = LightEntityFeature.TRANSITION

    def set_state(self, params: dict):
        """Set the state of the light based on provided parameters."""
        if self.param in params:
            self._attr_is_on = params[self.param] == "on"

    def get_params(self, brightness, color_temp, rgb_color, effect) -> dict:
        """Generate parameters for the light based on the provided settings."""
        pass

    async def async_turn_on(
        self,
        brightness: int = None,
        color_temp: int = None,
        rgb_color=None,
        xy_color=None,
        hs_color=None,
        effect: str = None,
        transition: float = None,
        **kwargs,
    ) -> None:
        """Turn the light on with optional settings like brightness and color."""
        if xy_color:
            rgb_color = color.color_xy_to_RGB(*xy_color)
        elif hs_color:
            rgb_color = color.color_hs_to_RGB(*hs_color)

        if transition:
            await self.transiton(brightness, color_temp, rgb_color, transition)
            return

        if brightness == 0:
            await self.async_turn_off()
            return

        if brightness or color_temp or rgb_color or effect:
            params = self.get_params(brightness, color_temp, rgb_color, effect)
        else:
            params = None

        if params:
            # some lights can only be turned on when the lights are off
            if not self.is_on:
                await self.ewelink.send(
                    self.device, {self.param: "on"}, query_cloud=False
                )

            await self.ewelink.send(
                self.device,
                params,
                {"cmd": "dimmable", **params},
                cmd_lan="dimmable",
                query_cloud=kwargs.get("query_cloud", True),
            )
        else:
            await self.ewelink.send(self.device, {self.param: "on"})

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off the light."""
        await self.ewelink.send(self.device, {self.param: "off"})

    async def transiton(
        self,
        brightness: int,
        color_temp: int,
        rgb_color,
        transition: float,
    ):
        """Transition the light from one state to another over time."""
        br0 = self.brightness or 0
        br1 = brightness
        ct0 = self.color_temp or self.min_mireds
        ct1 = color_temp
        rgb0 = self.rgb_color or [0, 0, 0]
        rgb1 = rgb_color

        t0 = time.time()

        while (k := (time.time() - t0) / transition) < 1:
            if br1 is not None:
                brightness = br0 + round((br1 - br0) * k)
            if ct1 is not None:
                color_temp = ct0 + round((ct1 - ct0) * k)
            if rgb1 is not None:
                rgb_color = [rgb0[i] + round((rgb1[i] - rgb0[i]) * k) for i in range(3)]

            await self.async_turn_on(
                brightness, color_temp, rgb_color, query_cloud=False
            )

        await self.async_turn_on(br1, ct1, rgb1)


# noinspection PyAbstractClass, UIID36
class XDimmer(XLight):
    """Represent a dimmable light with brightness control."""

    params = {"switch", "bright"}
    param = "switch"

    def set_state(self, params: dict):
        """Set the state of the dimmer light based on provided parameters."""
        XLight.set_state(self, params)
        if "bright" in params:
            self._attr_brightness = conv(params["bright"], 10, 100, 1, 255)

    def get_params(self, brightness, color_temp, rgb_color, effect) -> dict:
        """Generate parameters for the dimmer light based on brightness."""
        if brightness:
            return {"bright": conv(brightness, 1, 255, 10, 100)}


# noinspection PyAbstractClass, UIID57
class XLight57(XLight):
    """Represent a light with custom brightness control."""

    params = {"state", "channel0"}
    param = "state"

    def set_state(self, params: dict):
        """Set the state of the XLight57 based on provided parameters."""
        XLight.set_state(self, params)
        if "channel0" in params:
            self._attr_brightness = conv(params["channel0"], 25, 255, 1, 255)

    def get_params(self, brightness, color_temp, rgb_color, effect) -> dict:
        """Generate parameters for the XLight57 based on brightness."""
        if brightness:
            return {"channel0": str(conv(brightness, 1, 255, 25, 255))}


# noinspection PyAbstractClass, UIID44
class XLightD1(XLight):
    """Represent a light with limited brightness control."""

    params = {"switch", "brightness"}
    param = "switch"

    def set_state(self, params: dict):
        """Set the state of the XLightD1 based on provided parameters."""
        XLight.set_state(self, params)
        if "brightness" in params:
            self._attr_brightness = conv(params["brightness"], 0, 100, 1, 255)

    def get_params(self, brightness, color_temp, rgb_color, effect) -> dict:
        """Generate parameters for the XLightD1 based on brightness."""
        if brightness:
            # brightness can be only with switch=on in one message (error 400)
            # the purpose of the mode is unclear
            # max brightness=100 (error 400)
            return {
                "brightness": conv(brightness, 1, 255, 0, 100),
                "mode": 0,
                "switch": "on",
            }
###############################################################################
# Category 2. XLight base (color)
###############################################################################

UIID22_MODES = {
    "Good Night": {
        "channel0": "0",
        "channel1": "0",
        "channel2": "189",
        "channel3": "118",
        "channel4": "0",
        "zyx_mode": 3,
        "type": "middle",
    },
    "Reading": {
        "channel0": "0",
        "channel1": "0",
        "channel2": "255",
        "channel3": "255",
        "channel4": "255",
        "zyx_mode": 4,
        "type": "middle",
    },
    "Party": {
        "channel0": "0",
        "channel1": "0",
        "channel2": "207",
        "channel3": "56",
        "channel4": "3",
        "zyx_mode": 5,
        "type": "middle",
    },
    "Leisure": {
        "channel0": "0",
        "channel1": "0",
        "channel2": "56",
        "channel3": "85",
        "channel4": "179",
        "zyx_mode": 6,
        "type": "middle",
    },
}


# noinspection PyAbstractClass, UIID22
class XLightB1(XLight):
    """Represent a light with support for color temperature and RGB color modes."""

    params = {"state", "zyx_mode", "channel0", "channel2"}
    param = "state"

    _attr_min_mireds = 1  # cold
    _attr_max_mireds = 3  # warm
    _attr_effect_list = list(UIID22_MODES.keys())
    _attr_supported_color_modes = {ColorMode.COLOR_TEMP, ColorMode.RGB}
    _attr_supported_features = LightEntityFeature.EFFECT | LightEntityFeature.TRANSITION

    def set_state(self, params: dict):
        """Set the state of the XLightB1 based on provided parameters."""
        XLight.set_state(self, params)

        if "zyx_mode" in params:
            mode = params["zyx_mode"]
            if mode == 1:
                self._attr_color_mode = ColorMode.COLOR_TEMP
            else:
                self._attr_color_mode = ColorMode.RGB
            if mode >= 3:
                self._attr_effect = self.effect_list[mode - 3]
            else:
                self._attr_effect = None

        if self.color_mode == ColorMode.COLOR_TEMP:
            cold = int(params["channel0"])
            warm = int(params["channel1"])
            if warm == 0:
                self._attr_color_temp = 1
            elif cold == warm:
                self._attr_color_temp = 2
            elif cold == 0:
                self._attr_color_temp = 3
            self._attr_brightness = conv(max(cold, warm), 25, 255, 1, 255)

        else:
            self._attr_rgb_color = (
                int(params["channel2"]),
                int(params["channel3"]),
                int(params["channel4"]),
            )

    def get_params(self, brightness, color_temp, rgb_color, effect) -> dict:
        """Generate parameters for the XLightB1 based on brightness, color temperature, and RGB color."""
        if brightness or color_temp:
            ch = str(conv(brightness or self.brightness, 1, 255, 25, 255))
            if not color_temp:
                color_temp = self.color_temp
            if color_temp == 1:
                params = {"channel0": ch, "channel1": "0"}
            elif color_temp == 2:
                params = {"channel0": ch, "channel1": ch}
            elif color_temp == 3:
                params = {"channel0": ch, "channel1": ch}
            else:
                raise NotImplementedError

            return {
                **params,
                "channel2": "0",
                "channel3": "0",
                "channel4": "0",
                "zyx_mode": 1,
            }

        if rgb_color:
            return {
                "channel0": "0",
                "channel1": "0",
                "channel2": str(rgb_color[0]),
                "channel3": str(rgb_color[1]),
                "channel4": str(rgb_color[2]),
                "zyx_mode": 2,
            }

        if effect:
            return UIID22_MODES[effect]


class XZigbeeLight(XLight):
    """Manage the zigbee Light."""

    param = "switch"

    _attr_supported_color_modes = {ColorMode.COLOR_TEMP, ColorMode.HS}

    def set_state(self, params: dict):
        """Set the state of the light based on the provided parameters."""
        XLight.set_state(self, params)

        mode = params.get("colorMode")

        if mode == "cct":
            self._attr_color_mode = ColorMode.COLOR_TEMP
        elif mode == "rgb":
            self._attr_color_mode = ColorMode.HS

        if "colorTemp" in params:
            self._attr_color_temp = conv(
                params["colorTemp"],
                0,
                100,
                self._attr_max_mireds,  # yellow
                self._attr_min_mireds,  # blue
            )

        if br := params.get(f"{mode}Brightness"):
            self._attr_brightness = conv(br, 1, 100, 0, 255)

        if "hue" in params and "saturation" in params:
            self._attr_hs_color = (params["hue"], params["saturation"])

    async def async_turn_on(
        self,
        brightness: int = None,
        color_temp: int = None,
        hs_color: tuple = None,
        **kwargs,
    ) -> None:
        """Turn on the light with the specified settings."""
        params = {self.param: "on"}

        if color_temp is not None:
            params["colorMode"] = "cct"
            params["colorTemp"] = conv(
                color_temp, self._attr_max_mireds, self._attr_min_mireds, 0, 100
            )

        if hs_color is not None:
            params["colorMode"] = "rgb"
            params["hue"] = hs_color[0]
            params["saturation"] = hs_color[1]

        if brightness is not None:
            if "colorMode" not in params:
                if self._attr_color_mode == ColorMode.COLOR_TEMP:
                    params["colorMode"] = "cct"
                elif self._attr_color_mode == ColorMode.HS:
                    params["colorMode"] = "rgb"

            k = params["colorMode"] + "Brightness"  # cctBrightness or rgbBrightness
            params[k] = conv(brightness, 0, 255, 1, 100)

        await self.ewelink.send(self.device, params)


###############################################################################
# Category 3. Other
###############################################################################


# noinspection PyAbstractClass
class XLightGroup(XEntity, LightEntity):
    """Manage a group of lights with brightness adjustment."""

    params = {"switches"}
    channels: list = None

    _attr_brightness = 0
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def set_state(self, params: dict):
        """Set the state of the light group based on the provided parameters."""
        cnt = sum(
            1
            for i in params["switches"]
            if i["outlet"] in self.channels and i["switch"] == "on"
        )
        if cnt:
            self._attr_brightness = round(cnt / len(self.channels) * 255)
            self._attr_is_on = True
        else:
            self._attr_is_on = False

    async def async_turn_on(self, brightness: int = None, **kwargs):
        """Turn on the light group with the specified brightness."""
        if brightness is not None:
            self._attr_brightness = brightness
        elif self._attr_brightness == 0:
            self._attr_brightness = 255

        cnt = round(self._attr_brightness / 255 * len(self.channels))

        switches = [
            {"outlet": channel, "switch": "on" if i < cnt else "off"}
            for i, channel in enumerate(self.channels)
        ]
        await self.ewelink.send_bulk(self.device, {"switches": switches})

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off all channels in the light group."""
        switches = [{"outlet": ch, "switch": "off"} for ch in self.channels]
        await self.ewelink.send_bulk(self.device, {"switches": switches})


# noinspection PyAbstractClass, UIID22
class XFanLight(XOnOffLight):
    """Manage the XFan light."""

    params = {"switches", "light"}
    uid = "1"  # backward compatibility

    def set_state(self, params: dict):
        """Set the state of the fan light based on the provided parameters."""
        if "switches" in params:
            params = next(i for i in params["switches"] if i["outlet"] == 0)
            self._attr_is_on = params["switch"] == "on"
        else:
            self._attr_is_on = params["light"] == "on"

    async def async_turn_on(self, **kwargs):
        """Turn on the fan light."""
        params = {"switches": [{"outlet": 0, "switch": "on"}]}
        if self.device.get("localtype") == "fan_light":
            params_lan = {"light": "on"}
        else:
            params_lan = None
        await self.ewelink.send(self.device, params, params_lan)

    async def async_turn_off(self):
        """Turn off the fan light."""
        params = {"switches": [{"outlet": 0, "switch": "off"}]}
        if self.device.get("localtype") == "fan_light":
            params_lan = {"light": "off"}
        else:
            params_lan = None
        await self.ewelink.send(self.device, params, params_lan)


# noinspection PyAbstractClass, UIID25
class XDiffuserLight(XOnOffLight):
    """Represents the XDiffuserLight."""

    params = {"lightswitch", "lightbright", "lightmode", "lightRcolor"}

    _attr_effect_list = ["Color Light", "RGB Color", "Night Light"]
    _attr_supported_features = LightEntityFeature.EFFECT

    def set_state(self, params: dict):
        """Set the state of the diffuser light based on the provided parameters."""
        if "lightswitch" in params:
            self._attr_is_on = params["lightswitch"] == 1

        if "lightbright" in params:
            self._attr_brightness = conv(params["lightbright"], 0, 100, 1, 255)

        if "lightmode" in params:
            mode = params["lightmode"]
            if mode == 1:
                self._attr_color_mode = ColorMode.ONOFF
                self._attr_supported_color_modes = {ColorMode.ONOFF}
            elif mode == 2:
                self._attr_color_mode = ColorMode.RGB
                self._attr_supported_color_modes = {ColorMode.RGB}
            elif mode == 3:
                self._attr_color_mode = ColorMode.BRIGHTNESS
                self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}

        if "lightRcolor" in params:
            self._attr_rgb_color = (
                params["lightRcolor"],
                params["lightGcolor"],
                params["lightBcolor"],
            )

    async def async_turn_on(
        self, brightness: int = None, rgb_color=None, effect: str = None, **kwargs
    ) -> None:
        """Turn on the diffuser light with the specified settings."""

        params = {}

        if effect is not None:
            params["lightmode"] = mode = self.effect.index(effect) + 1
            if mode == 2 and rgb_color is None:
                rgb_color = self._attr_rgb_color

        if brightness is not None:
            params["lightbright"] = conv(brightness, 1, 255, 0, 100)

        if rgb_color is not None:
            params.update(
                {
                    "lightmode": 2,
                    "lightRcolor": rgb_color[0],
                    "lightGcolor": rgb_color[1],
                    "lightBcolor": rgb_color[2],
                }
            )

        if not params:
            params["lightswitch"] = 1

        await self.ewelink.send(self.device, params)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off the diffuser light."""
        await self.ewelink.send(self.device, {"lightswitch": 0})


T5_EFFECTS = {
    "Night Light": 0,
    "Party": 1,
    "Leisure": 2,
    "Color": 3,
    "Childhood": 4,
    "Wiper": 5,
    "Fairy": 6,
    "Starburst": 7,
    "DIY 1": 101,
    "DIY 2": 102,
}


class XT5Light(XOnOffLight):
    """Represents the XonXoffLight."""

    params = {"lightSwitch", "lightMode"}

    _attr_effect_list = list(T5_EFFECTS.keys())
    _attr_supported_features = LightEntityFeature.EFFECT

    def set_state(self, params: dict):
        """Set the state of the T5 light based on the provided parameters."""

        if "lightSwitch" in params:
            self._attr_is_on = params["lightSwitch"] == "on"

        if "lightMode" in params:
            self._attr_effect = next(
                (k for k, v in T5_EFFECTS.items() if v == params["lightMode"]), None
            )

    async def async_turn_on(
        self, brightness: int = None, effect: str = None, **kwargs
    ) -> None:
        """Turn on the T5 light with the specified settings."""

        params = {}

        if effect and effect in T5_EFFECTS:
            params["lightMode"] = T5_EFFECTS[effect]

        if not params:
            params["lightSwitch"] = "on"

        await self.ewelink.send(self.device, params)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off the T5 light."""

        await self.ewelink.send(self.device, {"lightSwitch": "off"})
