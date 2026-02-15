"""Support for Helvar light devices."""

from __future__ import annotations

import logging

import aiohelvar

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_XY_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.util import color as color_util

from .const import (
    COLOR_MODE_MIREDS,
    COLOR_MODE_XY,
    CONF_COLOR_MODE,
    CONF_FADE_TIME,
    DEFAULT_FADE_TIME,
    DOMAIN as HELVAR_DOMAIN,
)
from .group import async_setup_entry as setup_groups_entry

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(hass, config, add_entities, discovery_info=None):
    """Not currently used."""


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Helvar lights from a config entry."""
    router = hass.data[HELVAR_DOMAIN][config_entry.entry_id]
    configured_color_mode = config_entry.data.get(CONF_COLOR_MODE)
    fade_time = config_entry.options.get(CONF_FADE_TIME, DEFAULT_FADE_TIME)

    # Create individual light entities first so they are registered
    # in the entity registry before group entities reference them
    devices = [
        HelvarLight(device, router, configured_color_mode, fade_time)
        for device in router.api.devices.get_light_devices()
    ]

    _LOGGER.info("Adding %s helvar device lights", len(devices))
    async_add_entities(devices)

    # Set up group lights after individual lights are registered
    await setup_groups_entry(hass, config_entry, async_add_entities)


class HelvarLight(LightEntity):
    """Representation of a Helvar Light."""

    _attr_should_poll = False

    def __init__(
        self,
        device: aiohelvar.devices.Device,
        router,
        configured_color_mode: str | None,
        fade_time: int,
    ):
        """Initialize a Helvar light."""
        self.router = router
        self.device = device
        self._configured_color_mode = configured_color_mode
        self._fade_time = fade_time
        self._attr_color_temp_kelvin: int | None = None
        self._attr_xy_color: tuple[float, float] | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to device updates when added to hass."""

        async def async_router_callback_device(device):
            _LOGGER.debug("Received status update for %s", device)
            self.async_write_ha_state()

        self.router.api.devices.register_subscription(
            self.device.address, async_router_callback_device
        )

    @property
    def unique_id(self):
        """Return the unique ID of this Helvar light."""
        return f"{self.device.address}-light"

    @property
    def name(self):
        """Return the display name of this light."""
        return self.device.name

    @property
    def brightness(self):
        """Return the brightness of the light."""
        return self.device.brightness

    @property
    def is_on(self):
        """Return true if light is on."""
        return self.brightness > 0

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        """Return supported color modes."""
        if self.device.is_color and self._configured_color_mode == COLOR_MODE_XY:
            return {ColorMode.XY}
        if self.device.is_color and self._configured_color_mode == COLOR_MODE_MIREDS:
            return {ColorMode.COLOR_TEMP}
        return {ColorMode.BRIGHTNESS}

    @property
    def color_mode(self) -> ColorMode:
        """Return the active color mode."""
        if self.device.is_color and self._configured_color_mode == COLOR_MODE_XY:
            return ColorMode.XY
        if self.device.is_color and self._configured_color_mode == COLOR_MODE_MIREDS:
            return ColorMode.COLOR_TEMP
        return ColorMode.BRIGHTNESS

    @property
    def color_temp_kelvin(self) -> int | None:
        """Return the color temperature in Kelvin."""
        if self.color_mode == ColorMode.COLOR_TEMP:
            return self._attr_color_temp_kelvin
        return None

    @property
    def xy_color(self) -> tuple[float, float] | None:
        """Return the XY color value."""
        if self.color_mode == ColorMode.XY:
            return self._attr_xy_color
        return None

    async def async_turn_on(self, **kwargs):
        """Turn the light on with optional brightness and color."""
        brightness = kwargs.get(ATTR_BRIGHTNESS, 255)
        level = f"{((brightness / 255) * 100):.1f}"

        # Handle color temperature
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            kelvin = kwargs[ATTR_COLOR_TEMP_KELVIN]
            mireds = color_util.color_temperature_kelvin_to_mired(kelvin)
            self._attr_color_temp_kelvin = kelvin
            await self.router.api.devices.set_device_colour_temperature(
                self.device.address,
                int(mireds),
                level=level,
                fade_time=self._fade_time,
            )
            return

        # Handle XY color
        if ATTR_XY_COLOR in kwargs:
            xy = kwargs[ATTR_XY_COLOR]
            self._attr_xy_color = xy
            await self.router.api.devices.set_device_xy_color(
                self.device.address,
                xy[0],
                xy[1],
                level=level,
                fade_time=self._fade_time,
            )
            return

        await self.router.api.devices.set_device_brightness(
            self.device.address, brightness, fade_time=self._fade_time
        )

    async def async_turn_off(self, **kwargs):
        """Instruct the light to turn off."""
        await self.router.api.devices.set_device_brightness(
            self.device.address, 0, fade_time=self._fade_time
        )
