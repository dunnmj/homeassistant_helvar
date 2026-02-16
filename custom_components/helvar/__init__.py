"""The HelvarNet integration."""

from __future__ import annotations

import asyncio
import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import CONF_HOST, CONF_PORT, DEFAULT_PORT, DOMAIN
from .router import HelvarRouter

_LOGGER = logging.getLogger(__name__)

SERVICE_SEND_COMMAND = "send_command"
ATTR_COMMAND = "command"
ATTR_HOST = "host"

SERVICE_SEND_COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_COMMAND): cv.string,
        vol.Optional(ATTR_HOST): cv.string,
    }
)

PLATFORMS = ["light"]

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_HOST): cv.string,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass, config):
    """Set up the Helvar platform."""

    hass.data[DOMAIN] = {}

    async def handle_send_command(call: ServiceCall) -> None:
        """Send a raw HelvarNet ASCII command to one or all routers."""
        command: str = call.data[ATTR_COMMAND]
        target_host: str | None = call.data.get(ATTR_HOST)

        # Normalize: ensure the command has the required > prefix and # terminator
        if not command.startswith(">"):
            command = f">{command}"
        if not command.endswith("#"):
            command = f"{command}#"

        routers = [
            r
            for r in hass.data[DOMAIN].values()
            if r is not None and r.api is not None
        ]

        if target_host:
            routers = [r for r in routers if r.host == target_host]
            if not routers:
                _LOGGER.error(
                    "No connected Helvar router found with host %s", target_host
                )
                return

        for router in routers:
            _LOGGER.debug("Sending command to %s: %s", router.host, command)
            await router.api.send_string(command)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_COMMAND,
        handle_send_command,
        schema=SERVICE_SEND_COMMAND_SCHEMA,
    )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HelvarNet from a config entry."""

    router = HelvarRouter(hass, entry)

    hass.data[DOMAIN][entry.entry_id] = router

    if not await router.async_setup():
        hass.data[DOMAIN][entry.entry_id] = None
        return False

    # for platform in PLATFORMS:
    #     hass.async_create_task(
    #         hass.config_entries.async_forward_entry_setup(entry, platform)
    #     )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, platform)
                for platform in PLATFORMS
            ]
        )
    )
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
