import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Optional, Dict

from aiohttp import ClientConnectorError, ClientWebSocketResponse, WSMessage

from .base import SIGNAL_CONNECTED, SIGNAL_UPDATE, XDevice, XRegistryBase

_LOGGER = logging.getLogger(__name__)

# API and WebSocket URLs for different regions
API = {
    "cn": "https://cn-apia.coolkit.cn",
    "as": "https://as-apia.coolkit.cc",
    "us": "https://us-apia.coolkit.cc",
    "eu": "https://eu-apia.coolkit.cc",
}

WS = {
    "cn": "https://cn-dispa.coolkit.cn/dispatch/app",
    "as": "https://as-dispa.coolkit.cc/dispatch/app",
    "us": "https://us-dispa.coolkit.cc/dispatch/app",
    "eu": "https://eu-dispa.coolkit.cc/dispatch/app",
}

# Country codes and corresponding region mappings

REGIONS = {
    "+93": ("Afghanistan", "as"),
    "+355": ("Albania", "eu"),
    "+213": ("Algeria", "eu"),
    "+376": ("Andorra", "eu"),
    "+244": ("Angola", "eu"),
    "+1264": ("Anguilla", "us"),
    "+1268": ("Antigua and Barbuda", "as"),
    "+54": ("Argentina", "us"),
    "+374": ("Armenia", "as"),
    "+297": ("Aruba", "eu"),
    "+247": ("Ascension", "eu"),
    "+61": ("Australia", "us"),
    "+43": ("Austria", "eu"),
    "+994": ("Azerbaijan", "as"),
    "+1242": ("Bahamas", "us"),
    "+973": ("Bahrain", "as"),
    "+880": ("Bangladesh", "as"),
    "+1246": ("Barbados", "us"),
    "+375": ("Belarus", "eu"),
    "+32": ("Belgium", "eu"),
    "+501": ("Belize", "us"),
    "+229": ("Benin", "eu"),
    "+1441": ("Bermuda", "as"),
    "+591": ("Bolivia", "us"),
    "+387": ("Bosnia and Herzegovina", "eu"),
    "+267": ("Botswana", "eu"),
    "+55": ("Brazil", "us"),
    "+673": ("Brunei", "as"),
    "+359": ("Bulgaria", "eu"),
    "+226": ("Burkina Faso", "eu"),
    "+257": ("Burundi", "eu"),
    "+855": ("Cambodia", "as"),
    "+237": ("Cameroon", "eu"),
    "+238": ("Cape Verde Republic", "eu"),
    "+1345": ("Cayman Islands", "as"),
    "+236": ("Central African Republic", "eu"),
    "+235": ("Chad", "eu"),
    "+56": ("Chile", "us"),
    "+86": ("China", "cn"),
    "+57": ("Colombia", "us"),
    "+682": ("Cook Islands", "us"),
    "+506": ("Costa Rica", "us"),
    "+385": ("Croatia", "eu"),
    "+53": ("Cuba", "us"),
    "+357": ("Cyprus", "eu"),
    "+420": ("Czech", "eu"),
    "+243": ("Democratic Republic of Congo", "eu"),
    "+45": ("Denmark", "eu"),
    "+253": ("Djibouti", "eu"),
    "+1767": ("Dominica", "as"),
    "+1809": ("Dominican Republic", "us"),
    "+670": ("East Timor", "as"),
    "+684": ("Eastern Samoa (US)", "us"),
    "+593": ("Ecuador", "us"),
    "+20": ("Egypt", "eu"),
    "+503": ("El Salvador", "us"),
    "+372": ("Estonia", "eu"),
    "+251": ("Ethiopia", "eu"),
    "+298": ("Faroe Islands", "eu"),
    "+679": ("Fiji", "us"),
    "+358": ("Finland", "eu"),
    "+33": ("France", "eu"),
    "+594": ("French Guiana", "us"),
    "+689": ("French Polynesia", "as"),
    "+241": ("Gabon", "eu"),
    "+220": ("Gambia", "eu"),
    "+995": ("Georgia", "as"),
    "+49": ("Germany", "eu"),
    "+233": ("Ghana", "eu"),
    "+350": ("Gibraltar", "eu"),
    "+30": ("Greece", "eu"),
    "+299": ("Greenland", "us"),
    "+1473": ("Grenada", "as"),
    "+590": ("Guadeloupe", "us"),
    "+1671": ("Guam", "us"),
    "+502": ("Guatemala", "us"),
    "+240": ("Guinea", "eu"),
    "+224": ("Guinea", "eu"),
    "+592": ("Guyana", "us"),
    "+509": ("Haiti", "us"),
    "+504": ("Honduras", "us"),
    "+852": ("Hong Kong, China", "as"),
    "+36": ("Hungary", "eu"),
    "+354": ("Iceland", "eu"),
    "+91": ("India", "as"),
    "+62": ("Indonesia", "as"),
    "+98": ("Iran", "as"),
    "+353": ("Ireland", "eu"),
    "+269": ("Islamic Federal Republic of Comoros", "eu"),
    "+972": ("Israel", "as"),
    "+39": ("Italian", "eu"),
    "+225": ("Ivory Coast", "eu"),
    "+1876": ("Jamaica", "us"),
    "+81": ("Japan", "as"),
    "+962": ("Jordan", "as"),
    "+254": ("Kenya", "eu"),
    "+975": ("Kingdom of Bhutan", "as"),
    "+383": ("Kosovo", "eu"),
    "+965": ("Kuwait", "as"),
    "+996": ("Kyrgyzstan", "as"),
    "+856": ("Laos", "as"),
    "+371": ("Latvia", "eu"),
    "+961": ("Lebanon", "as"),
    "+266": ("Lesotho", "eu"),
    "+231": ("Liberia", "eu"),
    "+218": ("Libya", "eu"),
    "+423": ("Liechtenstein", "eu"),
    "+370": ("Lithuania", "eu"),
    "+352": ("Luxembourg", "eu"),
    "+853": ("Macau, China", "as"),
    "+261": ("Madagascar", "eu"),
    "+265": ("Malawi", "eu"),
    "+60": ("Malaysia", "as"),
    "+960": ("Maldives", "as"),
    "+223": ("Mali", "eu"),
    "+356": ("Malta", "eu"),
    "+596": ("Martinique", "us"),
    "+222": ("Mauritania", "eu"),
    "+230": ("Mauritius", "eu"),
    "+52": ("Mexico", "us"),
    "+373": ("Moldova", "eu"),
    "+377": ("Monaco", "eu"),
    "+976": ("Mongolia", "as"),
    "+382": ("Montenegro", "as"),
    "+1664": ("Montserrat", "as"),
    "+212": ("Morocco", "eu"),
    "+258": ("Mozambique", "eu"),
    "+95": ("Myanmar", "as"),
    "+264": ("Namibia", "eu"),
    "+977": ("Nepal", "as"),
    "+31": ("Netherlands", "eu"),
    "+599": ("Netherlands Antilles", "as"),
    "+687": ("New Caledonia", "as"),
    "+64": ("New Zealand", "us"),
    "+505": ("Nicaragua", "us"),
    "+227": ("Niger", "eu"),
    "+234": ("Nigeria", "eu"),
    "+47": ("Norway", "eu"),
    "+968": ("Oman", "as"),
    "+92": ("Pakistan", "as"),
    "+970": ("Palestine", "as"),
    "+507": ("Panama", "us"),
    "+675": ("Papua New Guinea", "as"),
    "+595": ("Paraguay", "us"),
    "+51": ("Peru", "us"),
    "+63": ("Philippines", "as"),
    "+48": ("Poland", "eu"),
    "+351": ("Portugal", "eu"),
    "+974": ("Qatar", "as"),
    "+242": ("Republic of Congo", "eu"),
    "+964": ("Republic of Iraq", "as"),
    "+389": ("Republic of Macedonia", "eu"),
    "+262": ("Reunion", "eu"),
    "+40": ("Romania", "eu"),
    "+7": ("Russia", "eu"),
    "+250": ("Rwanda", "eu"),
    "+1869": ("Saint Kitts and Nevis", "as"),
    "+1758": ("Saint Lucia", "us"),
    "+1784": ("Saint Vincent", "as"),
    "+378": ("San Marino", "eu"),
    "+239": ("Sao Tome and Principe", "eu"),
    "+966": ("Saudi Arabia", "as"),
    "+221": ("Senegal", "eu"),
    "+381": ("Serbia", "eu"),
    "+248": ("Seychelles", "eu"),
    "+232": ("Sierra Leone", "eu"),
    "+65": ("Singapore", "as"),
    "+421": ("Slovakia", "eu"),
    "+386": ("Slovenia", "eu"),
    "+27": ("South Africa", "eu"),
    "+82": ("South Korea", "as"),
    "+34": ("Spain", "eu"),
    "+94": ("Sri Lanka", "as"),
    "+249": ("Sultan", "eu"),
    "+597": ("Suriname", "us"),
    "+268": ("Swaziland", "eu"),
    "+46": ("Sweden", "eu"),
    "+41": ("Switzerland", "eu"),
    "+963": ("Syria", "as"),
    "+886": ("Taiwan, China", "as"),
    "+992": ("Tajikistan", "as"),
    "+255": ("Tanzania", "eu"),
    "+66": ("Thailand", "as"),
    "+228": ("Togo", "eu"),
    "+676": ("Tonga", "us"),
    "+1868": ("Trinidad and Tobago", "us"),
    "+216": ("Tunisia", "eu"),
    "+90": ("Turkey", "as"),
    "+993": ("Turkmenistan", "as"),
    "+1649": ("Turks and Caicos", "as"),
    "+44": ("UK", "eu"),
    "+256": ("Uganda", "eu"),
    "+380": ("Ukraine", "eu"),
    "+971": ("United Arab Emirates", "as"),
    "+1": ("United States", "us"),
    "+598": ("Uruguay", "us"),
    "+998": ("Uzbekistan", "as"),
    "+678": ("Vanuatu", "us"),
    "+58": ("Venezuela", "us"),
    "+84": ("Vietnam", "as"),
    "+685": ("Western Samoa", "us"),
    "+1340": ("Wilk Islands", "as"),
    "+967": ("Yemen", "as"),
    "+260": ("Zambia", "eu"),
    "+263": ("Zimbabwe", "eu"),
}

DATA_ERROR = {0: "online", 503: "offline", 504: "timeout", None: "unknown"}

APP = ["R8Oq3y0eSZSYdKccHlrQzT1ACCOUT9Gv"]

class AuthError(Exception):
    """Raise when authentication fails."""

    pass

class ResponseWaiter:
    """Handle response waiting logic."""

    _waiters: Dict[str, asyncio.Future] = {}

    def _set_response(self, sequence: str, error: int) -> bool:
        """Set response for a given sequence."""

        if sequence not in self._waiters:
            return False

        try:
            result = DATA_ERROR[error] if error in DATA_ERROR else f"E#{error}"
            self._waiters[sequence].set_result(result)
            return True
        except Exception:
            return False

    async def _wait_response(self, sequence: str, timeout: float):
        """Wait for response with a specific sequence and timeout."""

        self._waiters[sequence] = fut = asyncio.get_event_loop().create_future()

        try:
            await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            return "timeout"
        finally:
            _ = self._waiters.pop(sequence, None)

        return fut.result()

def sign(msg: bytes) -> bytes:
    """Generate a signed message."""

    try:
        return hmac.new(APP[1].encode(), msg, hashlib.sha256).digest()
    except IndexError:
        a = base64.b64encode(str(REGIONS).encode())
        s = "L8KDAMO6wpomxpYZwrHhu4AuEjQKBy8nwoMHNB7DmwoWwrvCsSYGw4wDAxs="
        return hmac.new(
            bytes(a[ord(c)] for c in base64.b64decode(s).decode()), msg, hashlib.sha256
        ).digest()

class XRegistryCloud(ResponseWaiter, XRegistryBase):
    """Manage cloud-based device registration and communication."""

    auth: dict | None = None
    devices: dict[str, dict] = None
    last_ts: float = 0
    online: bool | None = None
    region: str = None

    task: asyncio.Task | None = None
    ws: ClientWebSocketResponse = None

    @property
    def host(self) -> str:
        """Return the host URL for the current region."""

        return API[self.region]

    @property
    def ws_host(self) -> str:
        """Return the WebSocket URL for the current region."""

        return WS[self.region]

    @property
    def headers(self) -> dict:
        """Return request headers for authorization."""

        return {"Authorization": "Bearer " + self.auth["at"]}

    @property
    def token(self) -> str:
        """Return the token for the current session."""

        return self.region + ":" + self.auth["at"]

    @property
    def country_code(self) -> str:
        """Return the country code for the current user."""

        return self.auth["user"]["countryCode"]

    async def login(
        self, username: str, password: str, country_code: str = "+86", app: int = 0
    ) -> bool:
        """Login using username, password, and optional country code."""

        if username == "token":
            self.region, token = password.split(":")
            return await self.login_token(token, 1)

        self.region = REGIONS[country_code][1]
        payload = {"password": password, "countryCode": country_code}

        if "@" in username:
            payload["email"] = username
        elif username.startswith("+"):
            payload["phoneNumber"] = username
        else:
            payload["phoneNumber"] = "+" + username

        data = json.dumps(payload).encode()
        headers = {
            "Authorization": "Sign " + base64.b64encode(sign(data)).decode(),
            "Content-Type": "application/json",
            "X-CK-Appid": APP[0],
        }
        r = await self.session.post(
            self.host + "/v2/user/login", data=data, headers=headers, timeout=5
        )
        resp = await r.json()

        if resp["error"] == 10004:
            self.region = resp["data"]["region"]
            r = await self.session.post(
                self.host + "/v2/user/login", data=data, headers=headers, timeout=5
            )
            resp = await r.json()

        if resp["error"] != 0:
            raise AuthError(resp["msg"])

        self.auth = resp["data"]
        self.auth["appid"] = APP[0]

        return True

    async def login_token(self, token: str, app: int = 0) -> bool:
        """Login using a token."""

        headers = {"Authorization": "Bearer " + token, "X-CK-Appid": APP[0]}
        r = await self.session.get(
            self.host + "/v2/user/profile", headers=headers, timeout=5
        )
        resp = await r.json()
        if resp["error"] != 0:
            raise AuthError(resp["msg"])

        self.auth = resp["data"]
        self.auth["at"] = token
        self.auth["appid"] = APP[0]

        return True

    async def get_homes(self) -> dict:
        """Retrieve the list of homes associated with the account."""

        r = await self.session.get(
            self.host + "/v2/family", headers=self.headers, timeout=10
        )
        resp = await r.json()
        return {i["id"]: i["name"] for i in resp["data"]["familyList"]}

    async def get_devices(self, homes: list = None) -> list[dict]:
        """Retrieve the list of devices for a given home."""

        devices = []
        for home in homes or [None]:
            r = await self.session.get(
                self.host + "/v2/device/thing",
                headers=self.headers,
                timeout=10,
                params={"num": 0, "familyid": home} if home else {"num": 0},
            )
            resp = await r.json()
            if resp["error"] != 0:
                raise Exception(resp["msg"])
            devices += [
                i["itemData"]
                for i in resp["data"]["thingList"]
                if "deviceid" in i["itemData"]
            ]
        return devices

    async def send(
        self,
        device: XDevice,
        params: dict = None,
        sequence: str = None,
        timeout: float = 5,
    ):
        """Send a request or update to a device."""

        log = f"{device['deviceid']} => Cloud4 | "
        if params:
            log += f"{params} | "

        while (delay := self.last_ts + 0.1 - time.time()) > 0:
            log += "DDoS | "
            await asyncio.sleep(delay)
        self.last_ts = time.time()

        if sequence is None:
            sequence = await self.sequence()
        log += sequence

        _LOGGER.debug(log)
        try:
            payload = {
                "action": "update" if params else "query",
                "apikey": device["apikey"],
                "selfApikey": self.auth["user"]["apikey"],
                "deviceid": device["deviceid"],
                "params": params or [],
                "userAgent": "app",
                "sequence": sequence,
            }

            await self.ws.send_json(payload)

            if timeout:
                return await self._wait_response(sequence, timeout)
        except ConnectionResetError:
            return "offline"
        except Exception as e:
            _LOGGER.error(log, exc_info=e)
            return "E#???"

    def start(self, **kwargs):
        """Start the cloud service task."""

        self.task = asyncio.create_task(self.run_forever(**kwargs))

    async def stop(self):
        """Stop the cloud service task."""

        if self.task:
            self.task.cancel()
            self.task = None

        self.set_online(None)

    def set_online(self, value: Optional[bool]):
        """Set the online status of the cloud service."""

        _LOGGER.debug(f"CLOUD change state old={self.online}, new={value}") # noqa: G004
        if value == self.online:
            return
        self.online = value
        self.signal(SIGNAL_UPDATE)

    async def send_ws(self, msg: str) -> str:
        """Send a WebSocket message."""

        await self.ws.send_str(msg)
        return await self.ws.receive()

    async def receive(self) -> None:
        """Handle incoming WebSocket messages."""

        while True:
            try:
                msg = await self.ws.receive()
                if msg.type == WSMessage.TEXT:
                    message = msg.data
                    _LOGGER.debug(f"Received message: {message}") # noqa: G004
                    # handle message...
            except Exception as e:
                _LOGGER.error("Error receiving WebSocket message", exc_info=e)
                break

    async def run_forever(self, **kwargs):
        """Maintain WebSocket connection."""

        while True:
            try:
                self.ws = await self.session.ws_connect(self.ws_host, **kwargs)
                self.set_online(True)

                async for msg in self.ws:
                    if msg.type == WSMessage.TEXT:
                        await self.process_ws_message(msg.data)
            except Exception as e:
                _LOGGER.error(f"Error in WebSocket connection: {e}") # noqa: G004
                self.set_online(False)
                await asyncio.sleep(5)

    async def process_ws_message(self, message: str):
        """Process WebSocket message."""

        _LOGGER.debug(f"Processing WebSocket message: {message}")  # noqa: G004
        # Logic to process message...

    async def _process_ws_msg(self, data: dict):
        """Process WebSocket message data and handle actions."""

        if "action" not in data:
            # response on our command
            if "sequence" in data:
                self._set_response(data["sequence"], data.get("error"))

            # with params response on query, without - on update
            if "params" in data:
                self.dispatcher_send(SIGNAL_UPDATE, data)
            elif "config" in data:
                data["params"] = data.pop("config")
                self.dispatcher_send(SIGNAL_UPDATE, data)
            elif "error" in data:
                if data["error"] != 0:
                    _LOGGER.warning(f"Cloud ERROR: {data}") # noqa: G004
            else:
                _LOGGER.warning(f"UNKNOWN cloud msg: {data}") # noqa: G004

        elif data["action"] == "update":
            # new state from device
            self.dispatcher_send(SIGNAL_UPDATE, data)

        elif data["action"] == "sysmsg":
            # changed device online status
            self.dispatcher_send(SIGNAL_UPDATE, data)

        elif data["action"] == "reportSubDevice":
            # nothing useful: https://github.com/AlexxIT/SonoffLAN/issues/767
            pass

        else:
            _LOGGER.warning(f"UNKNOWN cloud msg: {data}") # noqa: G004

async def _ping(ws: ClientWebSocketResponse, heartbeat: int):
    """Send ping to WebSocket server at specified intervals."""

    try:
        while heartbeat:
            await asyncio.sleep(heartbeat)
            await ws.send_str("ping")
    except:
        pass
