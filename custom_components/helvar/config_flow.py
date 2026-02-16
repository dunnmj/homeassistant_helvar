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
    CONF_COLOR_MODES,
    CONF_FADE_TIME,
    CONF_HOST,
    CONF_PORT,
    DEFAULT_FADE_TIME,
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

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        """Get the options flow for this handler."""
        return OptionsFlowHandler()

    def __init__(self):
        """Initialize the Helvar flow."""
        self.router: aiohelvar.Router | None = None
        self._user_input: dict[str, Any] = {}
        self._title: str = ""
        self._color_devices: list = []
        self._color_modes: dict[str, str] = {}
        self._color_device_index: int = 0

    async def validate_input(
        self, hass: HomeAssistant, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Validate the user input allows us to connect.

        Data has the keys from STEP_USER_DATA_SCHEMA with values provided by
        the user.
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
            _LOGGER.warning(
                "Failed to discover devices during config flow; "
                "color light detection may be incomplete"
            )

        workgroup_name = router.workgroup_name
        self.router = router
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

        # Collect color-capable devices for per-device mode selection
        if self.router:
            self._color_devices = [
                device
                for device in self.router.devices.devices.values()
                if device.is_color
            ]

            if self._color_devices:
                _LOGGER.info(
                    "Found %d color control lights",
                    len(self._color_devices),
                )
                self._color_device_index = 0
                self._color_modes = {}
                return await self.async_step_color_mode()

        # No color lights — create entry directly
        _LOGGER.info("Creating Helvar config entry")
        return self.async_create_entry(title=self._title, data=self._user_input)

    async def async_step_color_mode(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask the user the color mode for each color-capable device."""
        if user_input is not None:
            device = self._color_devices[self._color_device_index]
            addr_key = str(device.address)
            self._color_modes[addr_key] = user_input[CONF_COLOR_MODE]
            self._color_device_index += 1

            # If more color devices remain, show next device
            if self._color_device_index < len(self._color_devices):
                return await self.async_step_color_mode()

            # All color devices configured — create entry
            self._user_input[CONF_COLOR_MODES] = self._color_modes
            _LOGGER.info(
                "Creating Helvar config entry with per-device color modes: %s",
                self._color_modes,
            )
            return self.async_create_entry(title=self._title, data=self._user_input)

        # Show form for the current color device
        device = self._color_devices[self._color_device_index]
        device_label = str(device.name or device.address)

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
            description_placeholders={"device_name": device_label},
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Helvar options flow."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        # Resolve current per-device color modes from options then data
        current_color_modes: dict[str, str] = self.config_entry.options.get(
            CONF_COLOR_MODES,
            self.config_entry.data.get(CONF_COLOR_MODES, {}),
        )

        # Get the live router to discover current color devices
        router = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        color_devices: list = []
        if router and hasattr(router, "api"):
            color_devices = [
                device
                for device in router.api.devices.devices.values()
                if device.is_color
            ]

        if user_input is not None:
            # Convert seconds to centiseconds for storage
            fade_seconds = user_input[CONF_FADE_TIME]
            options: dict[str, Any] = {CONF_FADE_TIME: int(fade_seconds * 100)}

            # Extract per-device color mode selections
            new_color_modes: dict[str, str] = {}
            for device in color_devices:
                field_key = f"color_mode_{device.address}"
                if field_key in user_input:
                    new_color_modes[str(device.address)] = user_input[field_key]
            if new_color_modes:
                options[CONF_COLOR_MODES] = new_color_modes

            return self.async_create_entry(title="", data=options)

        # Convert stored centiseconds back to seconds for display
        current_cs = self.config_entry.options.get(CONF_FADE_TIME, DEFAULT_FADE_TIME)
        current_seconds = current_cs / 100.0

        schema_fields: dict[Any, Any] = {
            vol.Required(CONF_FADE_TIME, default=current_seconds): vol.All(
                vol.Coerce(float), vol.Range(min=0, max=100)
            ),
        }

        # Add a color mode selector for each color-capable device
        for device in color_devices:
            addr_str = str(device.address)
            device_label = str(device.name or device.address)
            current_mode = current_color_modes.get(addr_str, COLOR_MODE_MIREDS)
            field_key = f"color_mode_{device.address}"
            schema_fields[
                vol.Optional(
                    field_key,
                    default=current_mode,
                    description={"suggested_value": current_mode},
                )
            ] = vol.In(COLOR_MODE_OPTIONS)

        options_schema = vol.Schema(schema_fields)

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
        )
