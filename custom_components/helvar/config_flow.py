"""Config flow for HelvarNet integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohelvar
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import (
    COLOR_MODE_MIREDS,
    COLOR_MODE_XY,
    CONF_COLOR_MODE,
    CONF_HOST,
    CONF_PORT,
    DEFAULT_PORT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
    }
)

COLOR_MODE_OPTIONS = {
    COLOR_MODE_MIREDS: "Mireds (color temperature)",
    COLOR_MODE_XY: "CX/CY (XY color space)",
}


@config_entries.HANDLERS.register(DOMAIN)
class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Helvar."""

    VERSION = 1

    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    def __init__(self):
        """Initialize the Helvar flow."""
        self.router: aiohelvar.Router | None = None
        self._user_input: dict[str, Any] = {}
        self._title: str = ""
        self._has_color_lights: bool = False

    async def validate_input(
        self, hass: HomeAssistant, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Validate the user input allows us to connect.

        Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
        """
        router = aiohelvar.Router((data[CONF_HOST]), data[CONF_PORT])

        try:
            await router.connect()
        except ConnectionError as initial_exception:
            raise CannotConnect() from initial_exception

        # Initialize to discover devices and check for color lights
        try:
            await router.initialize(discover_cluster=True, lights_only=True)
        except Exception:
            _LOGGER.debug("Failed to initialize during config flow, continuing")

        workgroup_name = router.workgroup_name
        self.router = router
        # Return info that you want to store in the config entry.
        return {"title": workgroup_name}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors = {}

        try:
            info = await self.validate_input(self.hass, user_input)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"

        if errors:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
            )

        self._user_input = user_input
        self._title = info["title"]

        # Check if there are any color control lights
        if self.router:
            color_lights = [
                device
                for device in self.router.devices.devices.values()
                if device.is_color
            ]
            self._has_color_lights = len(color_lights) > 0

            if self._has_color_lights:
                light_names = [
                    str(device.name or device.address) for device in color_lights
                ]
                _LOGGER.info(
                    "Found %d color control lights: %s",
                    len(color_lights),
                    ", ".join(light_names),
                )
                return await self.async_step_color_mode()

        # No color lights — create entry directly
        _LOGGER.info("Creating Helvar config entry")
        return self.async_create_entry(title=self._title, data=self._user_input)

    async def async_step_color_mode(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask the user how color control lights should be controlled."""
        if user_input is not None:
            self._user_input[CONF_COLOR_MODE] = user_input[CONF_COLOR_MODE]
            _LOGGER.info(
                "Creating Helvar config entry with color mode: %s",
                user_input[CONF_COLOR_MODE],
            )
            return self.async_create_entry(title=self._title, data=self._user_input)

        color_mode_schema = vol.Schema(
            {
                vol.Required(CONF_COLOR_MODE, default=COLOR_MODE_MIREDS): vol.In(
                    COLOR_MODE_OPTIONS
                ),
            }
        )

        return self.async_show_form(
            step_id="color_mode",
            data_schema=color_mode_schema,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
