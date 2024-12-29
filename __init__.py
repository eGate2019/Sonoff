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
from .core.ewelink.LoggingSession import LoggingSession

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
        ),
    },
    extra=vol.ALLOW_EXTRA,
)

UNIQUE_DEVICES = {}



async def remove_deactivated_entities(hass: HomeAssistant, integration_domain: str):
    """Remove deactivated entities for a given integration."""
    # Get the entity registry
    entity_registry = async_get_entity_registry(hass)

    # Iterate through entities related to the specified integration
    for entity_id, entity_entry in entity_registry.entities.items():
        if entity_entry.platform == integration_domain:
            # Check if the entity is disabled or unavailable
            if entity_entry.disabled:
                _LOGGER.info(f"Removing disabled entity: {entity_id}")  # noqa: G004
                # Remove the entity from the registry
                entity_registry.async_remove(entity_id)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    if (MAJOR_VERSION, MINOR_VERSION) < (2023, 2):
        raise Exception("unsupported hass version")

    # init storage for registries
    hass.data[DOMAIN] = {}

    # load optional global registry config
    if DOMAIN in config:
        XRegistry.config = conf = config[DOMAIN]
        if CONF_APPID in conf and CONF_APPSECRET in conf:
            APP[0] = conf[CONF_APPID]
            APP.append(conf[CONF_APPSECRET])
        if CONF_DEFAULT_CLASS in conf:
            core_devices.set_default_class(conf.get(CONF_DEFAULT_CLASS))
        if CONF_SENSORS in conf:
            core_devices.get_spec = core_devices.get_spec_wrapper(
                core_devices.get_spec, conf.get(CONF_SENSORS)
            )

    # cameras starts only on first command to it
    cameras = XCameras()

    try:
        # import ewelink account from YAML (first time)
        data = {
            CONF_USERNAME: XRegistry.config[CONF_USERNAME],
            CONF_PASSWORD: XRegistry.config[CONF_PASSWORD],
        }
        if not hass.config_entries.async_entries(DOMAIN):
            coro = hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_IMPORT}, data=data
            )
            hass.async_create_task(coro)
        await remove_deactivated_entities(hass, DOMAIN)
    except Exception as e:
        _LOGGER.info(f"Exception removing disabled entity: {e}")  # noqa: G004

    async def send_command(call: ServiceCall):
        """Service for send raw command to device.
        :param call: `device` - required param, all other params - optional
        """
        params = dict(call.data)
        deviceid = str(params.pop("device"))

        if len(deviceid) == 10:
            registry: XRegistry = next(
                r for r in hass.data[DOMAIN].values() if deviceid in r.devices
            )
            device = registry.devices[deviceid]

            # for debugging purposes
            if v := params.get("set_device"):
                device.update(v)
                return

            params_lan = params.pop("params_lan", None)
            command_lan = params.pop("command_lan", None)

            await registry.send(device, params, params_lan, command_lan)

        elif len(deviceid) == 6:
            await cameras.send(deviceid, params["cmd"])

        else:
            _LOGGER.error(f"Wrong deviceid {deviceid}")

    hass.services.async_register(DOMAIN, "send_command", send_command)

    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up a config entry for the integration."""
    # Enable debug logging if specified
    if config_entry.options.get("debug") and not _LOGGER.handlers:
        await system_health.setup_debug(hass, _LOGGER)

    # Get or create the registry for the config entry
    registry: XRegistry = hass.data[DOMAIN].get(config_entry.entry_id)
    if not registry:
        integration = hass.data["integrations"][DOMAIN]
        session = async_create_clientsession(
            hass,
            headers={"User-Agent": f"SonoffLAN/{integration.version}"}
        )
        debug_session = LoggingSession(session)
        registry = XRegistry(debug_session)
        hass.data[DOMAIN][config_entry.entry_id] = registry

    mode = config_entry.options.get(CONF_MODE, "auto")
    data = config_entry.data

    # Attempt cloud login if required
    if not registry.cloud.auth and data.get(CONF_PASSWORD):
        try:
            await registry.cloud.login(**data)
            if not data.get(CONF_COUNTRY_CODE):
                hass.config_entries.async_update_entry(
                    config_entry,
                    data={**data, CONF_COUNTRY_CODE: registry.cloud.country_code},
                )
        except Exception as e:
            _LOGGER.warning(f"Failed to log in using {mode} mode: {repr(e)}")
            if mode == "cloud":
                if isinstance(e, AuthError):
                    raise ConfigEntryAuthFailed(e)
                raise ConfigEntryNotReady(e)

    # Add an update listener if none exists
    if not config_entry.update_listeners:
        config_entry.add_update_listener(async_update_options)

    # Handle cleanup on Home Assistant stop
    config_entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, registry.stop)
    )

    # Forward entry setups for platforms
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    # Load or fetch devices
    devices: list[dict] | None = None
    store = Store(hass, 1, f"{DOMAIN}/{config_entry.data['username']}.json")
    if registry.cloud.auth:
        try:
            homes = config_entry.options.get("homes")
            devices = await registry.cloud.get_devices(homes)
            _LOGGER.debug(f"{len(devices)} devices loaded from the cloud")  # noqa: G004
            await store.async_save(devices)  # Cache devices
        except Exception as e:
            _LOGGER.warning("Failed to load devices from the cloud", exc_info=e)

    if not devices:
        devices = await store.async_load()
        if devices:
            _LOGGER.debug(f"{len(devices)} devices loaded from the cache")  # noqa: G004

    # Set up devices and entities
    entities = None
    if devices:
        devices = internal_unique_devices(config_entry.entry_id, devices)
        entities = registry.setup_devices(devices)

    # Start cloud or local mode as needed
    if mode in ("auto", "cloud") and config_entry.data.get(CONF_PASSWORD):
        registry.cloud.start(**config_entry.data)

    if mode in ("auto", "local"):
        zeroconf_instance = await zeroconf.async_get_instance(hass)
        registry.local.start(zeroconf_instance)

    _LOGGER.debug(f"{mode.upper()} mode started")

    # Handle initialization tasks
    if registry.cloud.task:
        await registry.cloud.dispatcher_wait(SIGNAL_CONNECTED)
    elif registry.local.online:
        await asyncio.sleep(3)

    # Add entities to the registry
    if entities:
        _LOGGER.debug(f"Adding {len(entities)} entities")
        registry.dispatcher_send(SIGNAL_ADD_ENTITIES, entities)

    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a specific configuration entry
    in Home Assistant asynchronously.

    :param hass: HomeAssistant
    :type hass: HomeAssistant
    :param entry: The `entry` parameter in the `async_unload_entry` function represents a configuration
    entry in Home Assistant. It contains information about a specific integration or component that has
    been set up in the system. This parameter is used to identify the entry that needs to be unloaded or
    removed during the unloading process
    :type entry: ConfigEntry
    """

    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    registry: XRegistry = hass.data[DOMAIN][entry.entry_id]
    await registry.stop()

    return ok


def internal_unique_devices(uid: str, devices: list) -> list:
    """For support multiple integrations - bind each device to one integraion.
    To avoid duplicates.
    """  # noqa: D205

    return [
        device
        for device in devices
        if UNIQUE_DEVICES.setdefault(device["deviceid"], uid) == uid
    ]


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device
) -> bool:
    device_registry(hass).async_remove_device(device.id)
    return True
