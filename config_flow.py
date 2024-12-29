from functools import lru_cache
import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_MODE, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .core.const import CONF_COUNTRY_CODE, CONF_DEBUG, CONF_MODES, DOMAIN
from .core.ewelink import XRegistryCloud
from .core.ewelink.cloud import REGIONS
from .core.ewelink.LoggingSession import LoggingSession

_LOGGER = logging.getLogger(__name__)


class FlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle the configuration flow for the integration."""

    @property
    @lru_cache(maxsize=1)
    def cloud(self):
        """Return an instance of XRegistryCloud for API interactions."""
        session = async_get_clientsession(self.hass)
        #debug_session = LoggingSession(session)
        return XRegistryCloud(session)

    async def async_step_import(self, user_input=None):
        """Handle import step from configuration.yaml."""
        return await self.async_step_user(user_input)

    async def async_step_user(self, user_input: dict = None):
        """Handle user input during setup."""
        codes = {k: f"{v[0]} | {k}" for k, v in REGIONS.items()}

        # Define the schema for user input validation
        data_schema = vol_schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Optional(CONF_PASSWORD): str,
                vol.Optional(CONF_COUNTRY_CODE): vol.In(codes),
            },
            user_input,
        )

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            password = user_input.get(CONF_PASSWORD)

            try:
                config_entry = await self.async_set_unique_id(username)

                if config_entry and password == "token":
                    # Special handling for token-based authentication
                    await self.cloud.login(**config_entry.data, app=1)
                    return self.async_show_form(
                        step_id="user",
                        data_schema=data_schema,
                        errors={"base": "template"},
                        description_placeholders={
                            "error": "Token: " + self.cloud.token
                        },
                    )

                if password:
                    await self.cloud.login(**user_input)

                if config_entry:
                    # Update existing entry with new data
                    self.hass.config_entries.async_update_entry(
                        config_entry, data=user_input, unique_id=self.unique_id
                    )
                    # Automatically reload the entry due to update listeners
                    return self.async_abort(reason="reauth_successful")

                # Create a new configuration entry
                return self.async_create_entry(title=username, data=user_input)

            except Exception as e:
                # Handle any exceptions that occur during login
                return self.async_show_form(
                    step_id="user",
                    data_schema=data_schema,
                    errors={"base": "template"},
                    description_placeholders={"error": str(e)},
                )

        # Show the form for user input if no input has been provided yet
        return self.async_show_form(step_id="user", data_schema=data_schema)

    async def async_step_reauth(self, user_input=None):
        """Handle reauthentication flow."""
        return await self.async_step_user()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        """Return the options flow handler for this integration."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(OptionsFlow):
    """Handle options flow for the integration."""

    def __init__(self, config_entry: ConfigEntry):
        """Initialize the options flow handler."""
        self.config_entry = config_entry

    async def async_step_init(self, data: dict = None):
        """Handle initialization of options configuration."""
        if data is not None:
            return self.async_create_entry(title="", data=data)

        homes = {}

        if self.config_entry.data.get(CONF_PASSWORD):
            try:
                # Use a separate account to retrieve user homes
                session = async_get_clientsession(self.hass)
                cloud = XRegistryCloud(session)
                await cloud.login(**self.config_entry.data, app=1)
                homes = await cloud.get_homes()
            except Exception as e:
                _LOGGER.error("Failed to retrieve homes: %s", str(e))

        # Ensure all homes in options are included in the retrieved homes list
        for home in self.config_entry.options.get("homes", []):
            if home not in homes:
                homes[home] = home

        # Define schema for options configuration validation
        data = vol_schema(
            {
                vol.Optional(CONF_MODE, default="auto"): vol.In(CONF_MODES),
                vol.Optional(CONF_DEBUG, default=False): bool,
                vol.Optional("homes"): cv.multi_select(homes),
            },
            dict(self.config_entry.options),
        )

        return self.async_show_form(step_id="init", data_schema=data)


def vol_schema(schema: dict, defaults: dict | None) -> vol.Schema:
    """Create a voluptuous schema with optional default values."""
    if defaults:
        for key in schema:
            if (value := defaults.get(key.schema)) is not None:
                key.default = vol.default_factory(value)
    return vol.Schema(schema)
