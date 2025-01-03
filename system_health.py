"""Provide info to system health."""

from collections import deque
from datetime import datetime
import logging
from logging import Logger
import re
import traceback
import uuid

from aiohttp import web

from homeassistant.components import system_health
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.system_info import async_get_system_info

from .core import xutils
from .core.const import DOMAIN, PRIVATE_KEYS


@callback
def async_register(
    hass: HomeAssistant, register: system_health.SystemHealthRegistration
) -> None:
    """Register the system health information callback."""
    register.async_register_info(system_health_info)


async def system_health_info(hass: HomeAssistant):
    """Collect system health information for display in the UI."""
    cloud_online = local_online = cloud_total = local_total = 0

    for registry in hass.data[DOMAIN].values():
        for device in registry.devices.values():
            if "online" in device:
                cloud_total += 1
                if registry.cloud.online and device["online"]:
                    cloud_online += 1
            # localtype - all discovered local devices
            # host - all online local devices (maybe encrypted)
            # params - all local unencrypted devices
            if "localtype" in device:
                local_total += 1
                if "host" in device and "params" in device:
                    local_online += 1

    source_hash = await hass.async_add_executor_job(xutils.source_hash)

    integration = hass.data["integrations"][DOMAIN]
    info = {
        "version": f"{integration.version} ({source_hash})",
        "cloud_online": f"{cloud_online} / {cloud_total}",
        "local_online": f"{local_online} / {local_total}",
    }

    if DebugView.url:
        info["debug"] = {"type": "failed", "error": "", "more_info": DebugView.url}

    return info


async def setup_debug(hass: HomeAssistant, logger: Logger):
    """Set up the debug view for system health and logs."""
    view = DebugView(logger)
    hass.http.register_view(view)

    source_hash = await hass.async_add_executor_job(xutils.source_hash)

    integration = hass.data["integrations"][DOMAIN]
    info = await async_get_system_info(hass)
    info[DOMAIN + "_version"] = f"{integration.version} ({source_hash})"
    logger.debug(f"SysInfo: {info}")  # noqa: G004

    integration.manifest["issue_tracker"] = view.url


class DebugView(logging.Handler, HomeAssistantView):
    """Generate a web page with component debug logs."""

    name = DOMAIN
    requires_auth = False

    def __init__(self, logger: Logger)->None:
        """Initialize the debug view and set up logging handler."""
        super().__init__()

        # https://waymoot.org/home/python_string/
        self.text = deque(maxlen=10000)

        self.propagate_level = logger.getEffectiveLevel()

        # Random URL because it's without authorization
        DebugView.url = f"/api/{DOMAIN}/{uuid.uuid4()}"

        logger.addHandler(self)
        logger.setLevel(logging.DEBUG)

    def handle(self, rec: logging.LogRecord):
        """Handle a log record and add it to the debug view."""
        if isinstance(rec.args, dict):
            rec.msg = rec.msg % {
                k: v for k, v in rec.args.items() if k not in PRIVATE_KEYS
            }
        dt = datetime.fromtimestamp(rec.created).strftime("%Y-%m-%d %H:%M:%S")
        msg = f"{dt} [{rec.levelname[0]}] {rec.msg}"
        if rec.exc_info:
            exc = traceback.format_exception(*rec.exc_info, limit=1)
            msg += "|" + "".join(exc[-2:]).replace("\n", "|")
        self.text.append(msg)

        # Prevent debug from being logged in Hass log if user doesn't want it
        if self.propagate_level > rec.levelno:
            rec.levelno = -1

    async def get(self, request: web.Request):
        """Handle an HTTP GET request for debug logs."""
        try:
            lines = self.text

            if "q" in request.query:
                reg = re.compile(rf"({request.query['q']})", re.IGNORECASE)
                lines = [p for p in lines if reg.search(p)]

            if "t" in request.query:
                tail = int(request.query["t"])
                lines = lines[-tail:]

            body = "\n".join(lines)
            r = request.query.get("r", "")

            return web.Response(
                text="<!DOCTYPE html><html>"
                f'<head><meta http-equiv="refresh" content="{r}"></head>'
                f"<body><pre>{body}</pre></body>"
                "</html>",
                content_type="text/html",
            )
        except Exception:
            return web.Response(status=500)
