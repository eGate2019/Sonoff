"""Remote module."""

import asyncio
import logging
from typing import Union

from homeassistant.components.remote import (
    ATTR_DELAY_SECS,
    DEFAULT_DELAY_SECS,
    RemoteEntity,
)
from homeassistant.const import ATTR_COMMAND
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity

from .binary_sensor import XRemoteSensor, XRemoteSensorOff
from .button import XRemoteButton
from .core.const import DOMAIN
from .core.entity import XEntity
from .core.ewelink import SIGNAL_ADD_ENTITIES, XRegistry

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0  # fix entity_platform parallel_updates Semaphore


async def async_setup_entry(hass: HomeAssistant, config_entry, add_entities):
    """Set up remote entities for the given config entry."""
    ewelink: XRegistry = hass.data[DOMAIN][config_entry.entry_id]
    ewelink.dispatcher_connect(
        SIGNAL_ADD_ENTITIES,
        lambda x: add_entities([e for e in x if isinstance(e, RemoteEntity)]),
    )


def rfbridge_childs(remotes: list, config: dict = None):
    """Generate child entities for the RFBridge based on remotes and config."""
    childs = {}
    duals = {}

    for remote in remotes:
        for button in remote["buttonName"]:
            channel = next(iter(button))

            if remote["remote_type"] != "6":
                child = {"name": button[channel], "device_class": "button"}
            else:
                child = {"name": remote["name"]}

            if config and child["name"] in config:
                child.update(config[child["name"]])

                if "payload_off" in child:
                    duals[channel] = child["payload_off"]

                if child.get("device_class") == "button" and (
                    "payload_off" in child or "timeout" in child
                ):
                    child.pop("device_class")

            child["channel"] = channel
            childs[channel] = child

    for ch, name in duals.items():
        try:
            ch_off = next(k for k, v in childs.items() if v["name"] == name)
        except StopIteration:
            _LOGGER.warning(f"Can't find payload_off: {name}") # noqa: G004
            continue
        childs[ch_off] = childs.pop(ch_off)
        childs[ch_off]["channel_on"] = ch

    return childs


# noinspection PyAbstractClass
class XRemote(XEntity, RemoteEntity):
    """Represent a remote entity with child buttons and sensors."""

    _attr_is_on = True
    childs: dict[str, Union[XRemoteButton, XRemoteSensor, XRemoteSensorOff]] = None

    def __init__(self, ewelink: XRegistry, device: dict)->None:
        """Initialize the remote entity with child sensors and buttons."""
        try:
            channels = [str(c["rfChl"]) for c in device["params"]["rfList"]]

            config = ewelink.config and ewelink.config.get("rfbridge")
            childs = rfbridge_childs(device["tags"]["zyx_info"], config)
            for ch, child in list(childs.items()):
                if ch not in channels:
                    childs.pop(ch)
                    continue

                if "channel_on" in child:
                    sensor = childs[child["channel_on"]]
                    childs[ch] = XRemoteSensorOff(child, sensor)
                elif child.get("device_class") == "button":
                    childs[ch] = XRemoteButton(ewelink, device, child)
                else:
                    childs[ch] = XRemoteSensor(ewelink, device, child)
            ewelink.dispatcher_send(SIGNAL_ADD_ENTITIES, childs.values())
            self.childs = childs

        except Exception as e:
            _LOGGER.error(f"{self.unique_id} | can't setup RFBridge", exc_info=e)  # noqa: G004

        XEntity.__init__(self, ewelink, device)

        self.params = {"cmd", "arming"}
        self.ts = None

    def set_state(self, params: dict):
        """Set the state of the remote entity based on the provided parameters."""
        if not self.is_on or "init" in params or not self.hass:
            return

        for param, ts in params.items():
            if not param.startswith("rfTrig"):
                continue

            if self.ts is None and params.get("arming"):
                self.ts = ts
                return

            if ts == self.ts:
                return

            self.ts = ts

            child = self.childs.get(param[6:])
            if not child:
                return
            child.internal_update(ts)

            self._attr_extra_state_attributes = data = {
                "command": int(child.channel),
                "name": child.name,
                "entity_id": self.entity_id,
                "ts": ts,
            }
            self.hass.bus.async_fire("sonoff.remote", data)

    def internal_available(self) -> bool:
        """Check if the remote entity and its children are available."""
        available = XEntity.internal_available(self)
        if self.childs and self.available != available:
            for child in self.childs.values():
                if not isinstance(child, Entity):
                    continue
                child._attr_available = available
                if child.hass:
                    child._async_write_ha_state()
        return available

    async def async_send_command(self, command, **kwargs):
        """Send a command to the remote entity with an optional delay."""
        delay = kwargs.get(ATTR_DELAY_SECS, DEFAULT_DELAY_SECS)
        for i, channel in enumerate(command):
            if i:
                await asyncio.sleep(delay)

            if not channel.isdigit():
                channel = next(k for k, v in self.childs.items() if v.name == channel)

            await self.ewelink.send(
                self.device,
                {"cmd": "transmit", "rfChl": int(channel)},
                cmd_lan="transmit",
            )

    async def async_learn_command(self, **kwargs):
        """Learn a new command from the remote."""
        command = kwargs[ATTR_COMMAND]
        await self.ewelink.send(
            self.device, {"cmd": "capture", "rfChl": int(command[0])}, cmd_lan="capture"
        )

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the remote entity on."""
        self._attr_is_on = True
        self._async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the remote entity off."""
        self._attr_is_on = False
        self._async_write_ha_state()
