"""Support for Helvar light devices."""

from __future__ import annotations

import logging
from typing import Any

import aiohelvar

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_XY_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import color as color_util

from .const import (
    COLOR_MODE_MIREDS,
    COLOR_MODE_XY,
    CONF_COLOR_MODE,
    CONF_FADE_TIME,
    DEFAULT_FADE_TIME,
    DOMAIN as HELVAR_DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(hass, config, add_entities, discovery_info=None):
    """Not currently used."""


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Helvar lights from a config entry."""

    router = hass.data[HELVAR_DOMAIN][config_entry.entry_id]
    configured_color_mode = config_entry.data.get(CONF_COLOR_MODE)
    fade_time = config_entry.options.get(CONF_FADE_TIME, DEFAULT_FADE_TIME)

    # Create individual light entities
    devices = [
        HelvarLight(device, router, configured_color_mode, fade_time)
        for device in router.api.devices.get_light_devices()
    ]

    # Create group light entities
    groups = [
        HelvarGroupLight(group, router, configured_color_mode, fade_time)
        for group in router.api.groups.groups.values()
    ]

    _LOGGER.info(
        "Adding %s helvar device lights and %s group lights",
        len(devices),
        len(groups),
    )

    async_add_entities(devices + groups)


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


class HelvarGroupLight(LightEntity):
    """Representation of a Helvar Group as a light entity.

    Aggregates state from member devices and sends native group-level
    commands (Direct Level Group, command 13) for control.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:lightbulb-group"

    def __init__(
        self,
        group: aiohelvar.groups.Group,
        router,
        configured_color_mode: str | None,
        fade_time: int,
    ):
        """Initialize a Helvar group light."""
        self.router = router
        self.group = group
        self._configured_color_mode = configured_color_mode
        self._fade_time = fade_time
        self._attr_color_temp_kelvin: int | None = None
        self._attr_xy_color: tuple[float, float] | None = None
        self._attr_brightness: int | None = None

        # Compute supported color modes from member capabilities
        self._update_values()

    def _get_member_devices(self) -> list[aiohelvar.devices.Device]:
        """Return the list of member Device objects."""
        devices = []
        for addr in self.group.devices:
            device = self.router.api.devices.devices.get(addr)
            if device is not None:
                devices.append(device)
        return devices

    async def async_added_to_hass(self) -> None:
        """Subscribe to member device updates and group updates."""

        async def async_member_callback(device):
            """Handle member device state change."""
            self._update_values()
            self.async_write_ha_state()

        # Subscribe to each member device
        for addr in self.group.devices:
            self.router.api.devices.register_subscription(addr, async_member_callback)

        # Subscribe to group-level updates (scene recalls, etc.)
        async def async_group_callback():
            """Handle group-level state change."""
            self._update_values()
            self.async_write_ha_state()

        self.router.api.groups.register_subscription(
            self.group.group_id, async_group_callback
        )

    @callback
    def _update_values(self) -> None:
        """Aggregate state from member devices (Hue pattern)."""
        members = self._get_member_devices()
        if not members:
            return

        supported_color_modes: set[ColorMode] = set()
        has_color = False
        has_color_temp = False
        has_dimming = False

        on_brightness_total = 0.0
        on_brightness_count = 0

        for device in members:
            if device.is_color:
                has_color = True
                if self._configured_color_mode == COLOR_MODE_XY:
                    supported_color_modes.add(ColorMode.XY)
                if self._configured_color_mode == COLOR_MODE_MIREDS:
                    supported_color_modes.add(ColorMode.COLOR_TEMP)
            if device.is_load:
                has_dimming = True
                if device.load_level > 0:
                    on_brightness_total += device.brightness
                    on_brightness_count += 1

        if not supported_color_modes and has_dimming:
            supported_color_modes.add(ColorMode.BRIGHTNESS)
        if not supported_color_modes:
            supported_color_modes.add(ColorMode.ONOFF)

        self._attr_supported_color_modes = supported_color_modes

        # Average brightness of on members
        if on_brightness_count > 0:
            self._attr_brightness = round(on_brightness_total / on_brightness_count)
        else:
            self._attr_brightness = 0

        # Determine active color mode
        if ColorMode.XY in supported_color_modes:
            self._attr_color_mode = ColorMode.XY
        elif ColorMode.COLOR_TEMP in supported_color_modes:
            self._attr_color_mode = ColorMode.COLOR_TEMP
        elif ColorMode.BRIGHTNESS in supported_color_modes:
            self._attr_color_mode = ColorMode.BRIGHTNESS
        else:
            self._attr_color_mode = ColorMode.ONOFF

    @property
    def unique_id(self):
        """Return the unique ID of this group light."""
        return f"helvar-group-{self.group.group_id}"

    @property
    def name(self):
        """Return the display name of this group light."""
        return self.group.name

    @property
    def is_on(self) -> bool:
        """Return true if any member is on."""
        return any(device.load_level > 0 for device in self._get_member_devices())

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the optional state attributes.

        Exposes member entity IDs and names following the Hue pattern.
        """
        members = self._get_member_devices()
        light_names: set[str] = set()
        light_entities: set[str] = set()

        ent_reg = er.async_get(self.hass)
        for device in members:
            if device.name:
                light_names.add(device.name)
            # Look up the HA entity ID for this member device
            entity_id = ent_reg.async_get_entity_id(
                "light",
                HELVAR_DOMAIN,
                f"{device.address}-light",
            )
            if entity_id:
                light_entities.add(entity_id)

        return {
            "is_helvar_group": True,
            "lights": light_names,
            "entity_id": light_entities,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the group on with optional brightness and color."""
        brightness = kwargs.get(ATTR_BRIGHTNESS)

        if brightness is None:
            # Use current brightness if only changing colour, else 255
            brightness = self._attr_brightness if self._attr_brightness else 255

        level = f"{((brightness / 255) * 100):.1f}"

        # Handle color temperature
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            kelvin = kwargs[ATTR_COLOR_TEMP_KELVIN]
            mireds = color_util.color_temperature_kelvin_to_mired(kelvin)
            self._attr_color_temp_kelvin = kelvin
            await self.router.api.groups.set_group_colour_temperature(
                self.group.group_id,
                level,
                int(mireds),
                fade_time=self._fade_time,
            )
            return

        # Handle XY color
        if ATTR_XY_COLOR in kwargs:
            xy = kwargs[ATTR_XY_COLOR]
            self._attr_xy_color = xy
            await self.router.api.groups.set_group_xy_color(
                self.group.group_id,
                level,
                xy[0],
                xy[1],
                fade_time=self._fade_time,
            )
            return

        await self.router.api.groups.set_group_level(
            self.group.group_id,
            level,
            fade_time=self._fade_time,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the group off."""
        await self.router.api.groups.set_group_level(
            self.group.group_id,
            "0",
            fade_time=self._fade_time,
        )
