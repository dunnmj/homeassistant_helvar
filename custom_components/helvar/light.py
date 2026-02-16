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
from homeassistant.helpers import entity_registry as er
from homeassistant.util import color as color_util, slugify

from .const import (
    COLOR_MODE_MIREDS,
    COLOR_MODE_NONE,
    COLOR_MODE_XY,
    CONF_COLOR_MODES,
    CONF_FADE_TIME,
    DEFAULT_FADE_TIME,
    DOMAIN as HELVAR_DOMAIN,
)
from .group import create_group_entities

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(hass, config, add_entities, discovery_info=None):
    """Not currently used."""


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Helvar lights from a config entry."""
    router = hass.data[HELVAR_DOMAIN][config_entry.entry_id]
    # Per-device color modes: options override data
    color_modes: dict[str, str] = config_entry.options.get(
        CONF_COLOR_MODES, config_entry.data.get(CONF_COLOR_MODES, {})
    )
    fade_time = config_entry.options.get(CONF_FADE_TIME, DEFAULT_FADE_TIME)

    devices = [
        HelvarLight(device, router, color_modes.get(str(device.address)), fade_time)
        for device in router.api.devices.get_light_devices()
    ]
    groups = create_group_entities(router, color_modes, fade_time)

    # Migrate stale group entity_ids before adding entities.
    # We do this now, while nothing is in the state machine yet, because
    # async_update_entity requires the target entity_id to be absent from
    # both the registry and the live state machine.
    ent_reg = er.async_get(hass)
    for group_entity in groups:
        if group_entity.group.name:
            desired_id = f"light.{slugify(group_entity.group.name)}_group"
            current_id = ent_reg.async_get_entity_id(
                "light", HELVAR_DOMAIN, group_entity.unique_id
            )
            if current_id and current_id != desired_id:
                try:
                    ent_reg.async_update_entity(current_id, new_entity_id=desired_id)
                    _LOGGER.debug(
                        "Renamed group entity %s -> %s", current_id, desired_id
                    )
                except ValueError:
                    # desired_id already taken by another entity — remove the stale
                    # entry so async_get_or_create re-registers it from the group
                    # name suggestion, auto-suffixing (_2, _3 …) if still needed.
                    _LOGGER.debug(
                        "Could not rename group entity %s to %s (conflict); "
                        "removing stale entry for re-registration",
                        current_id,
                        desired_id,
                    )
                    ent_reg.async_remove(current_id)

    _LOGGER.info(
        "Adding %s helvar device lights and %s group lights",
        len(devices),
        len(groups),
    )

    # Add all entities in a single batch with individual lights first,
    # so they are registered in the entity registry before group
    # entities look up member entity IDs in their attributes.
    async_add_entities([*devices, *groups])


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
        if self.device.is_color:
            if self._configured_color_mode == COLOR_MODE_XY:
                return {ColorMode.XY}
            if self._configured_color_mode == COLOR_MODE_NONE:
                return {ColorMode.BRIGHTNESS}
            return {ColorMode.COLOR_TEMP}
        return {ColorMode.BRIGHTNESS}

    @property
    def color_mode(self) -> ColorMode:
        """Return the active color mode."""
        if self.device.is_color:
            if self._configured_color_mode == COLOR_MODE_XY:
                return ColorMode.XY
            if self._configured_color_mode == COLOR_MODE_NONE:
                return ColorMode.BRIGHTNESS
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
