"""Base classes for X integration."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
import time
from typing import Optional

from aiohttp import ClientSession

SIGNAL_CONNECTED = "connected"
SIGNAL_UPDATE = "update"


class XDevice(dict):
    """Representation of an X device."""

    def __init__(self, *args, **kwargs)->None:
        """Initialize the XDevice."""
        super().__init__(*args, **kwargs)
        self.setdefault("params", {})
        self.setdefault("extra", {})

    @property
    def device_id(self) -> str:
        """Return the device ID."""
        return self["deviceid"]

    @property
    def name(self) -> str:
        """Return the device name."""
        return self["name"]

    @property
    def brand_name(self) -> Optional[str]:
        """Return the brand name."""
        return self.get("brandName")

    @property
    def product_model(self) -> Optional[str]:
        """Return the product model."""
        return self.get("productModel")

    @property
    def online(self) -> Optional[bool]:
        """Return if the device is online."""
        return self.get("online")

    @property
    def api_key(self) -> Optional[str]:
        """Return the API key."""
        return self.get("apikey")

    @property
    def local(self) -> Optional[bool]:
        """Return if the device is local."""
        return self.get("local")

    @property
    def local_type(self) -> Optional[str]:
        """Return the local device type."""
        return self.get("localtype")

    @property
    def host(self) -> Optional[str]:
        """Return the device host."""
        return self.get("host")

    @property
    def device_key(self) -> Optional[str]:
        """Return the device key."""
        return self.get("devicekey")

    @property
    def local_ts(self) -> Optional[float]:
        """Return the timestamp of the last local message."""
        return self.get("local_ts")

    @property
    def params_bulk(self) -> Optional[dict]:
        """Return the bulk parameters."""
        return self.get("params_bulk")

    @property
    def pow_ts(self) -> Optional[float]:
        """Return the power timestamp."""
        return self.get("pow_ts")

    @property
    def parent(self) -> Optional[dict]:
        """Return the parent device information."""
        return self.get("parent")


class XRegistryBase:
    """Base class for X registry."""

    def __init__(self, session: ClientSession) -> None:
        """Initialize the XRegistryBase."""
        self.dispatcher: dict[str, list[Callable]] = {}
        self.session = session
        self._sequence = 0
        self._sequence_lock = asyncio.Lock()

    async def sequence(self) -> str:
        """Return sequence counter in ms. Always unique."""
        t = time.time_ns() // 1_000_000
        async with self._sequence_lock:
            if t > self._sequence:
                self._sequence = t
            else:
                self._sequence += 1
            return str(self._sequence)

    def dispatcher_connect(self, signal: str, target: Callable) -> Callable:
        """Connect a dispatcher to a signal."""
        targets = self.dispatcher.setdefault(signal, [])
        if target not in targets:
            targets.append(target)
        return lambda: targets.remove(target)

    def dispatcher_send(self, signal: str, *args, **kwargs) -> None:
        """Send a signal to all connected dispatchers."""
        if not self.dispatcher.get(signal):
            return
        for handler in self.dispatcher[signal]:
            handler(*args, **kwargs)

    async def dispatcher_wait(self, signal: str) -> None:
        """Wait for a dispatcher signal."""
        event = asyncio.Event()
        disconnect = self.dispatcher_connect(signal, lambda: event.set())
        await event.wait()
        disconnect()
