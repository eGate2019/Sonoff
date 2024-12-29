# homeassistant/components/ewelink/registry.py

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Union

from aiohttp import ClientSession

from .base import SIGNAL_CONNECTED, SIGNAL_UPDATE, XDevice, XRegistryBase
from .cloud import XRegistryCloud
from .local import XRegistryLocal
import contextlib

_LOGGER = logging.getLogger(__name__)

SIGNAL_ADD_ENTITIES = "add_entities"
LOCAL_TTL = 60


class XRegistry(XRegistryBase):
    """Manages devices in the eWeLink integration, handling both cloud and local communications."""

    config: Dict[str, Any] = None
    task: Optional[asyncio.Task] = None

    def __init__(self, session: ClientSession)->None:
        """Initialize the instance."""

        super().__init__(session)

        self.devices: Dict[str, XDevice] = {}

        self.cloud = XRegistryCloud(session)
        self.cloud.dispatcher_connect(SIGNAL_CONNECTED, self.cloud_connected)
        self.cloud.dispatcher_connect(SIGNAL_UPDATE, self.cloud_update)

        self.local = XRegistryLocal(session)
        self.local.dispatcher_connect(SIGNAL_CONNECTED, self.local_connected)
        self.local.dispatcher_connect(SIGNAL_UPDATE, self.local_update)

    def setup_devices(self, devices: List[XDevice]) -> List[Any]:
        """Set up devices, assigning specifications and entities.

        Args:
            devices (List[XDevice]): List of device objects to set up.

        Returns:
            List[Any]: Entities associated with the devices.
        """
        from ..devices import get_spec

        entities = []

        for device in devices:
            did = device["deviceid"]
            with contextlib.suppress(Exception):
                device.update(self.config["devices"][did])

            try:
                uiid = device["extra"]["uiid"]
                _LOGGER.debug(f"{did} UIID {uiid:04} | %s", device["params"])  # noqa: G004

                if parentid := device["params"].get("parentid"):
                    with contextlib.suppress(StopIteration):
                        device["parent"] = next(
                            d for d in devices if d["deviceid"] == parentid
                        )

                entities += [cls(self, device) for cls in get_spec(device)]
                self.devices[did] = device

            except Exception as e:
                _LOGGER.warning(f"{did} !! can't setup device", exc_info=e)  # noqa: G004

        return entities

    @property
    def online(self) -> bool:
        """Check if the registry is online."""
        return self.cloud.online is not None or self.local.online

    async def stop(self, *args):
        """Stop the registry and clean up resources."""
        self.devices.clear()
        self.dispatcher.clear()

        await self.cloud.stop()
        await self.local.stop()

        if self.task:
            self.task.cancel()

    async def send(
        self,
        device: XDevice,
        params: Optional[Dict] = None,
        params_lan: Optional[Dict] = None,
        cmd_lan: Optional[str] = None,
        query_cloud: bool = True,
        timeout_lan: int = 1,
    ):
        """Send a command to a device via LAN or Cloud.

        Args:
            device (XDevice): The target device.
            params (Optional[Dict]): Parameters for the command.
            params_lan (Optional[Dict]): LAN-specific parameters.
            cmd_lan (Optional[str]): LAN-specific command.
            query_cloud (bool): Whether to query Cloud after sending.
            timeout_lan (int): Timeout for LAN communication.
        """
        seq = await self.sequence()

        if "parent" in device:
            main_device = device["parent"]
            if params_lan is None and params is not None:
                params_lan = params.copy()
            if params_lan:
                params_lan["subDevId"] = device["deviceid"]
        else:
            main_device = device

        can_local = self.can_local(device)
        can_cloud = self.can_cloud(device)

        if can_local and can_cloud:
            ok = await self.local.send(
                main_device, params_lan or params, cmd_lan, seq, timeout_lan
            )
            if ok != "online":
                ok = await self.cloud.send(device, params, seq)
                if ok != "online":
                    asyncio.create_task(self.check_offline(main_device))
                elif query_cloud and params:
                    await self.cloud.send(device, timeout=0)

        elif can_local:
            ok = await self.local.send(main_device, params_lan or params, cmd_lan, seq)
            if ok != "online":
                asyncio.create_task(self.check_offline(main_device))

        elif can_cloud:
            ok = await self.cloud.send(device, params, seq)
            if ok == "online" and query_cloud and params:
                await self.cloud.send(device, timeout=0)

    async def send_bulk(self, device: XDevice, params: Dict):
        """Send a bulk update to a device."""
        assert "switches" in params

        if "params_bulk" in device:
            for new in params["switches"]:
                for old in device["params_bulk"]["switches"]:
                    if new["outlet"] == old["outlet"]:
                        old["switch"] = new["switch"]
                        break
                else:
                    device["params_bulk"]["switches"].append(new)
        else:
            device["params_bulk"] = params

        await asyncio.sleep(0.1)

        if params := device.pop("params_bulk", None):
            return await self.send(device, params)

    async def send_cloud(self, device: XDevice, params: Dict = None, query=True):
        """Send a command to the device via the Cloud."""
        if not self.can_cloud(device):
            return
        ok = await self.cloud.send(device, params)
        if ok == "online" and query and params:
            await self.cloud.send(device, timeout=0)

    async def check_offline(self, device: XDevice):
        """Check if a device is offline."""
        if not device.get("host"):
            return

        for i in range(3):
            if i > 0:
                await asyncio.sleep(5)

            ok = await self.local.send(device, command="getState")
            if ok in ("online", "error"):
                device["local_ts"] = time.time() + LOCAL_TTL
                device["local"] = True
                return

            if time.time() > device.get("local_ts", 0) + LOCAL_TTL:
                break

        device["local"] = False
        did = device["deviceid"]
        _LOGGER.debug(f"{did} !! Local4 | Device offline")
        self.dispatcher_send(did)

    def cloud_connected(self):
        """Handle cloud connection events."""
        for deviceid in self.devices.keys():
            self.dispatcher_send(deviceid)

        if not self.task:
            self.task = asyncio.create_task(self.run_forever())

    def local_connected(self):
        """Handle local connection events."""
        if not self.task:
            self.task = asyncio.create_task(self.run_forever())

    def cloud_update(self, msg: Dict):
        """Handle cloud update messages."""
        did = msg["deviceid"]
        device = self.devices.get(did)

        if not device or "online" not in device:
            return

        params = msg["params"]
        _LOGGER.debug(f"{did} <= Cloud3 | %s | {msg.get('sequence')}", params)

        if "online" in params:
            device["online"] = params["online"]
            asyncio.create_task(self.check_offline(device))
        elif device["online"] is False:
            device["online"] = True

        if "sledOnline" in params:
            device["params"]["sledOnline"] = params["sledOnline"]

        self.dispatcher_send(did, params)

    def local_update(self, msg: Dict):
        """Handle local update messages."""
        mainid: str = msg["deviceid"]
        device: Optional[XDevice] = self.devices.get(mainid)
        params: Optional[Dict] = msg.get("params")

        # If the device is unknown, attempt to set it up
        if not device:
            if not params:
                try:
                    msg["params"] = params = self.local.decrypt_msg(
                        msg, self.config["devices"][mainid]["devicekey"]
                    )
                except Exception:
                    _LOGGER.debug(f"{mainid} !! skip setup for encrypted device")
                    self.devices[mainid] = msg  # Avoid repeated decryption attempts
                    return

            from ..devices import setup_diy
            device = setup_diy(msg)
            entities = self.setup_devices([device])
            self.dispatcher_send(SIGNAL_ADD_ENTITIES, entities)

        elif not params:
            if "devicekey" not in device:
                return
            try:
                params = self.local.decrypt_msg(msg, device["devicekey"])
            except Exception as e:
                _LOGGER.debug("Can't decrypt message", exc_info=e)
                return

        elif "devicekey" in device:
            device.pop("devicekey")

        realid = msg.get("subdevid", mainid)
        tag = "Local3" if "host" in msg else "Local0"

        _LOGGER.debug(
            f"{realid} <= {tag} | {msg.get('host', '')} | %s | {msg.get('seq', '')}",
            params,
        )

        if "sledOnline" in params:
            device["params"]["sledOnline"] = params["sledOnline"]

        if "host" in msg and device.get("host") != msg["host"]:
            device["host"] = params["host"] = msg["host"]
            device["localtype"] = msg["localtype"]

        device["local_ts"] = time.time() + LOCAL_TTL
        device["local"] = True

        self.dispatcher_send(realid, params)

        if realid != mainid:
            self.dispatcher_send(mainid, None)

    async def run_forever(self):
        """Run a daemon task for periodic updates and device pings."""
        while True:
            for device in self.devices.values():
                try:
                    self.update_device(device)
                except Exception as e:
                    _LOGGER.warning("Error in run_forever", exc_info=e)
            await asyncio.sleep(30)

    def update_device(self, device: XDevice):
        """Update a device based on its type and capabilities."""
        if "extra" not in device:
            return

        uiid = device["extra"]["uiid"]

        # Device-specific update logic
        if uiid in (5, 32, 182, 190, 181, 226):  # POW devices
            if self.can_cloud(device):
                params = {"uiActive": 60}
                asyncio.create_task(self.cloud.send(device, params, timeout=0))

        elif uiid == 126:  # DUALR3
            if self.can_local(device):
                asyncio.create_task(self.local.send(device, command="statistics"))
            elif self.can_cloud(device):
                params = {"uiActive": {"all": 1, "time": 60}}
                asyncio.create_task(self.cloud.send(device, params, timeout=0))

        elif uiid == 130:  # SPM-4Relay
            if self.can_cloud(device):
                asyncio.create_task(self.update_spm_pow(device))

        if "local_ts" in device and device["local_ts"] <= time.time():
            if self.local.online:
                asyncio.create_task(self.check_offline(device))

    async def update_spm_pow(self, device: XDevice):
        """Send periodic updates for SPM-4Relay devices."""
        for i in range(4):
            if i > 0:
                await asyncio.sleep(5)
            params = {"uiActive": {"outlet": i, "time": 60}}
            await self.cloud.send(device, params, timeout=0)

    def can_cloud(self, device: XDevice) -> bool:
        """Check if a device can communicate via the Cloud."""
        return self.cloud.online and device.get("online")

    def can_local(self, device: XDevice) -> bool:
        """Check if a device can communicate via LAN."""
        if not self.local.online:
            return False
        if "parent" in device:
            return device["parent"].get("local", False)
        return device.get("local", False)
