"""Support for Helvar group lights."""

from __future__ import annotations

from typing import Any

import aiohelvar

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_XY_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.util import color as color_util, slugify

from .const import (
    COLOR_MODE_NONE,
    COLOR_MODE_XY,
    DOMAIN as HELVAR_DOMAIN,
)


def create_group_entities(
    router, color_modes: dict[str, str], fade_time: int
) -> list[HelvarGroupLight]:
    """Create Helvar group light entities."""
    return [
        HelvarGroupLight(group, router, color_modes, fade_time)
        for group in router.api.groups.groups.values()
    ]


class HelvarGroupLight(LightEntity):
    """Representation of a Helvar Group as a light entity.

    Aggregates state from member devices and sends native group-level
    commands (Direct Level Group, command 13) for control.
    """

    _attr_should_poll = False
    _attr_icon = "mdi:lightbulb-group"

    def __init__(
        self,
        group: aiohelvar.groups.Group,
        router,
        color_modes: dict[str, str],
        fade_time: int,
    ):
        """Initialize a Helvar group light."""
        self.router = router
        self.group = group
        self._color_modes = color_modes
        self._fade_time = fade_time
        self._attr_color_temp_kelvin: int | None = None
        self._attr_xy_color: tuple[float, float] | None = None
        self._attr_brightness: int | None = None

        # Derive entity_id from the Helvar group name so it matches the display
        # name rather than the unique_id slug. This overrides any stale entity_id
        # stored in the entity registry from before group names were loaded.
        if group.name:
            self.entity_id = f"light.{slugify(group.name)}_group"

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
        async def async_group_callback(group):
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
        has_dimming = False

        on_brightness_total = 0.0
        on_brightness_count = 0

        for device in members:
            if device.is_color:
                device_mode = self._color_modes.get(str(device.address))
                if device_mode == COLOR_MODE_NONE:
                    # Treat this color device as brightness-only per user config
                    pass
                elif device_mode == COLOR_MODE_XY:
                    supported_color_modes.add(ColorMode.XY)
                else:
                    # Default to COLOR_TEMP for color devices
                    supported_color_modes.add(ColorMode.COLOR_TEMP)
            if device.is_load and not device.is_switch:
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

    @callback
    def _get_member_names_and_entity_ids(
        self,
    ) -> tuple[set[str], set[str]]:
        """Return the names and entity IDs for group member devices."""
        ent_reg = er.async_get(self.hass)
        light_names: set[str] = set()
        light_entities: set[str] = set()
        for device in self._get_member_devices():
            if device.name:
                light_names.add(device.name)
            if entity_id := ent_reg.async_get_entity_id(
                self.platform.domain,
                HELVAR_DOMAIN,
                f"{device.address}-light",
            ):
                light_entities.add(entity_id)
        return light_names, light_entities

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the optional state attributes.

        Exposes member entity IDs and names following the Hue pattern.
        """
        light_names, light_entities = self._get_member_names_and_entity_ids()
        return {
            "is_helvar_group": True,
            "helvar_group_id": self.group.group_id,
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
