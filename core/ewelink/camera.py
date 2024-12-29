"""Camera module."""

import asyncio
from dataclasses import dataclass
import logging
import socket
from threading import Thread
import time
from typing import Union

_LOGGER = logging.getLogger(__name__)

BROADCAST = ("255.255.255.255", 32108)

CMD_HELLO = "f130 0000"
CMD_PONG = "f1e1 0000"
CMD_DATA_ACK = "f1d1 0006 d100 0001"

COMMANDS = {
    "init": (
        "f1d0 0064 d100 0000 8888767648000000100000000000000000000000"
        "000000003132333435363738000000000000000000000000000000000000"
        "000000000000000000000000000000000000000000000000000000000000"
        "00000000000000000000000000000000"
    ),
    "left": (
        "f1d0 0024 d100 %s 888876760800000001100000000000000000000000"
        "000000 0608000000000000"
    ),
    "right": (
        "f1d0 0024 d100 %s 888876760800000001100000000000000000000000"
        "000000 0308000000000000"
    ),
    "up": (
        "f1d0 0024 d100 %s 888876760800000001100000000000000000000000"
        "000000 0208000000000000"
    ),
    "down": (
        "f1d0 0024 d100 %s 888876760800000001100000000000000000000000"
        "000000 0108000000000000"
    ),
}


@dataclass
class Camera:
    """Represent a camera device."""

    addr: tuple = None
    init_data: bytes = None
    last_time: int = 0
    sequence = 0
    wait_event = asyncio.Event()
    wait_data: int = None
    wait_sequence: bytes = b"\x00\x00"

    def init(self):
        """Initialize camera data."""
        self.sequence = 0
        self.wait_sequence = b"\x00\x00"

    def get_sequence(self) -> str:
        """Generate a new sequence number."""
        self.sequence += 1
        self.wait_sequence = self.sequence.to_bytes(2, byteorder="big")
        return self.wait_sequence.hex()

    async def wait(self, data: int):
        """Wait for a specific data response."""
        self.wait_data = data
        self.wait_event.clear()
        await self.wait_event.wait()


class XCameras(Thread):
    """Handle communication with multiple cameras."""

    devices: dict[str, Camera] = {}
    sock: socket = None

    def __init__(self)->None:
        """Initialize the XCameras thread."""
        super().__init__(name="Sonoff_CAM", daemon=True)

    def datagram_received(self, data: bytes, addr: tuple):
        """Handle incoming datagram from a camera."""
        cmd = data[1]

        if cmd == 0x41:
            deviceid = int.from_bytes(data[12:16], byteorder="big")
            deviceid = f"{deviceid:06}"

            if deviceid not in self.devices:
                _LOGGER.debug(f"Found new camera {deviceid}: {addr}") # noqa: G004
                self.devices[deviceid] = Camera(addr, data)
                return

            else:
                self.devices[deviceid].addr = addr
                self.devices[deviceid].init_data = data

        device = next((p for p in self.devices.values() if p.addr == addr), None)
        if not device:
            return

        if cmd != 0xE0:
            device.last_time = time.time()

        if cmd == 0xD0:
            data = bytes.fromhex(CMD_DATA_ACK) + data[6:8]
            self.sendto(data, device)

        elif cmd == 0xE0:
            pass

        if device.wait_data == cmd:
            if cmd != 0xD1 or device.wait_sequence == data[8:10]:
                device.wait_event.set()

    def sendto(self, data: Union[bytes, str], device: Camera):
        """Send data to a specific camera."""
        if isinstance(data, str):
            if "%s" in data:
                data = data % device.get_sequence()
            data = bytes.fromhex(data)
        self.sock.sendto(data, device.addr)

    def start(self):
        """Start the XCameras thread and initialize the socket."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind(("", 0))
        super().start()

    async def send(self, deviceid: str, command: str):
        """Send a command to a specific camera."""
        device = self.devices.get(deviceid)

        if not device or time.time() - device.last_time > 9:
            if not self.is_alive():
                self.start()

            if not device:
                self.devices[deviceid] = device = Camera()
            else:
                device.init()

            _LOGGER.debug("Send HELLO")
            data = bytes.fromhex(CMD_HELLO)
            self.sock.sendto(data, BROADCAST)
            await device.wait(0x41)

            _LOGGER.debug("Send UID Session Open Request")
            self.sendto(device.init_data, device)
            await device.wait(0x42)

            _LOGGER.debug("Send Init Command")
            self.sendto(COMMANDS["init"], device)
            await device.wait(0xD1)

        _LOGGER.debug(f"Send Command {command}")  # noqa: G004
        self.sendto(COMMANDS[command], device)
        await device.wait(0xD1)

    def run(self):
        """Run the XCameras thread to receive camera data."""
        while True:
            try:
                data, addr = self.sock.recvfrom(1024)
                self.datagram_received(data, addr)
            except Exception as e:
                _LOGGER.error("Camera read exception", exc_info=e)
