import asyncio
import logging

from aiohttp import ClientSession
import voluptuous as vol

from homeassistant.components import zeroconf
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import (
    CONF_DEVICE_CLASS,
    CONF_DEVICES,
    CONF_MODE,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PAYLOAD_OFF,
    CONF_SENSORS,
    CONF_TIMEOUT,
    CONF_USERNAME,
    EVENT_HOMEASSISTANT_STOP,
    MAJOR_VERSION,
    MINOR_VERSION,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.device_registry import async_get as device_registry
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.storage import Store

from . import system_health
from .core import devices as core_devices
from .core.const import (
    CONF_APPID,
    CONF_APPSECRET,
    CONF_COUNTRY_CODE,
    CONF_DEFAULT_CLASS,
    CONF_DEVICEKEY,
    CONF_RFBRIDGE,
    DOMAIN,
)
from .core.ewelink import SIGNAL_ADD_ENTITIES, SIGNAL_CONNECTED, XRegistry
from .core.ewelink.camera import XCameras
from .core.ewelink.cloud import APP, AuthError

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    "binary_sensor",
    "button",
    "climate",
    "cover",
    "fan",
    "light",
    "remote",
    "sensor",
    "switch",
    "number",
]

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_APPID): cv.string,
                vol.Optional(CONF_APPSECRET): cv.string,
                vol.Optional(CONF_USERNAME): cv.string,
                vol.Optional(CONF_PASSWORD): cv.string,
                vol.Optional(CONF_DEFAULT_CLASS): cv.string,
                vol.Optional(CONF_SENSORS): cv.ensure_list,
                vol.Optional(CONF_RFBRIDGE): {
                    cv.string: vol.Schema(
                        {
                            vol.Optional(CONF_NAME): cv.string,
                            vol.Optional(CONF_DEVICE_CLASS): cv.string,
                            vol.Optional(CONF_TIMEOUT, default=120): cv.positive_int,
                            vol.Optional(CONF_PAYLOAD_OFF): cv.string,
                        },
                        extra=vol.ALLOW_EXTRA,
                    ),
                },
                vol.Optional(CONF_DEVICES): {
                    cv.string: vol.Schema(
                        {
                            vol.Optional(CONF_NAME): cv.string,
                            vol.Optional(CONF_DEVICE_CLASS): vol.Any(str, list),
                            vol.Optional(CONF_DEVICEKEY): cv.string,
                        },
                        extra=vol.ALLOW_EXTRA,
                    ),
                },
            },
            extra=vol.ALLOW_EXTRA,
        )
    },
    extra=vol.ALLOW_EXTRA,
)

UNIQUE_DEVICES = {}


async def remove_deactivated_entities(hass: HomeAssistant, integration_domain: str):
    """Remove deactivated entities for a given integration."""
    entity_registry = async_get_entity_registry(hass)
    entity_list= entity_registry.entities.items()
    for entity_id, entity_entry in entity_list:
        if entity_entry.platform == integration_domain and entity_entry.disabled:
            _LOGGER.info("Removing disabled entity: %s", entity_id)
            entity_registry.async_remove(entity_id)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration from YAML configuration."""
    if (MAJOR_VERSION, MINOR_VERSION) < (2023, 2):
        raise Exception("Unsupported Home Assistant version")

    hass.data[DOMAIN] = {}

    if DOMAIN in config:
        XRegistry.config = conf = config[DOMAIN]
        if CONF_APPID in conf and CONF_APPSECRET in conf:
            APP[0] = conf[CONF_APPID]
            APP.append(conf[CONF_APPSECRET])
        if CONF_DEFAULT_CLASS in conf:
            core_devices.set_default_class(conf[CONF_DEFAULT_CLASS])
        if CONF_SENSORS in conf:
            core_devices.get_spec = core_devices.get_spec_wrapper(
                core_devices.get_spec, conf[CONF_SENSORS]
            )

    cameras = XCameras()

    try:
        if DOMAIN in config:
            data = {
                CONF_USERNAME: config[DOMAIN][CONF_USERNAME],
                CONF_PASSWORD: config[DOMAIN][CONF_PASSWORD],
            }
            if not hass.config_entries.async_entries(DOMAIN):
                await hass.config_entries.flow.async_init(
                    DOMAIN, context={"source": SOURCE_IMPORT}, data=data
                )
            await remove_deactivated_entities(hass, DOMAIN)
    except Exception as e:
        _LOGGER.exception("Error during setup: %s", e)

    async def send_command(call: ServiceCall):
        """Service to send raw command to a device."""
        params = dict(call.data)
        deviceid = str(params.pop("device"))

        if len(deviceid) == 10:
            registry = next(
                (r for r in hass.data[DOMAIN].values() if deviceid in r.devices), None
            )
            if not registry:
                _LOGGER.error("Device not found: %s", deviceid)
                return

            device = registry.devices[deviceid]
            if params.get("set_device"):
                device.update(params.pop("set_device"))
                return

            await registry.send(device, params)

        elif len(deviceid) == 6:
            await cameras.send(deviceid, params["cmd"])

        else:
            _LOGGER.error("Invalid device ID: %s", deviceid)

    hass.services.async_register(DOMAIN, "send_command", send_command)
    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up a config entry for the integration."""
    if config_entry.options.get("debug"):
        await system_health.setup_debug(hass, _LOGGER)

    registry = hass.data[DOMAIN].get(config_entry.entry_id)
    if not registry:
        integration = hass.data["integrations"].get(DOMAIN)
        session = async_create_clientsession(
            hass, headers={"User-Agent": f"SonoffLAN/{integration.version}"}
        )
        registry = XRegistry(session)
        hass.data[DOMAIN][config_entry.entry_id] = registry

    mode = config_entry.options.get(CONF_MODE, "auto")

    if not registry.cloud.auth and config_entry.data.get(CONF_PASSWORD):
        try:
            await registry.cloud.login(**config_entry.data)
        except AuthError as err:
            raise ConfigEntryAuthFailed from err
        except Exception as err:
            _LOGGER.warning("Cloud login failed: %s", err)
            if mode == "cloud":
                raise ConfigEntryNotReady from err

    config_entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, registry.stop)
    )

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    devices = None
    store = Store(hass, 1, f"{DOMAIN}/{config_entry.data[CONF_USERNAME]}.json")
    if registry.cloud.auth:
        try:
            devices = await registry.cloud.get_devices(config_entry.options.get("homes"))
            await store.async_save(devices)
        except Exception as e:
            _LOGGER.warning("Failed to fetch devices from cloud: %s", e)

    if not devices:
        devices = await store.async_load()

    if devices:
        devices = internal_unique_devices(config_entry.entry_id, devices)
        registry.setup_devices(devices)

    if mode in ("auto", "cloud") and config_entry.data.get(CONF_PASSWORD):
        registry.cloud.start(**config_entry.data)

    if mode in ("auto", "local"):
        zeroconf_instance = await zeroconf.async_get_instance(hass)
        registry.local.start(zeroconf_instance)

    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry):
    """Update the options."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    registry = hass.data[DOMAIN].pop(entry.entry_id, None)
    if registry:
        await registry.stop()

    return ok


def internal_unique_devices(uid: str, devices: list) -> list:
    """Ensure unique devices across multiple integrations."""
    return [
        device
        for device in devices
        if UNIQUE_DEVICES.setdefault(device["deviceid"], uid) == uid
    ]


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device
) -> bool:
    """Remove a device associated with a config entry."""
    device_registry(hass).async_remove_device(device.id)
    return True
