"""Tests for the Helvar group light platform."""

import pytest
from unittest.mock import Mock, AsyncMock, MagicMock, patch

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode

from custom_components.helvar.group import HelvarGroupLight, async_setup_entry
from custom_components.helvar.const import DOMAIN as HELVAR_DOMAIN


def _make_mock_device(
    address="1.2.3.4",
    name="Test Light",
    brightness=128,
    load_level=50.0,
    is_color=False,
    is_load=True,
):
    """Create a mock Helvar device with configurable attributes."""
    device = Mock()
    device.address = address
    device.name = name
    device.brightness = brightness
    device.load_level = load_level
    device.is_color = is_color
    device.is_load = is_load
    return device


def _make_mock_group(group_id=5, name="Group 5", device_addresses=None):
    """Create a mock Helvar group."""
    group = Mock()
    group.group_id = group_id
    group.name = name
    group.devices = device_addresses or []
    return group


def _make_mock_router(devices_dict=None):
    """Create a mock router with devices and groups."""
    router = Mock()
    router.api = Mock()
    router.api.devices = Mock()
    router.api.devices.devices = devices_dict or {}
    router.api.devices.register_subscription = Mock()
    router.api.groups = Mock()
    router.api.groups.register_subscription = Mock()
    router.api.groups.set_group_level = AsyncMock()
    router.api.groups.set_group_colour_temperature = AsyncMock()
    router.api.groups.set_group_xy_color = AsyncMock()
    return router


class TestHelvarGroupLight:
    """Test the HelvarGroupLight class."""

    def test_unique_id(self):
        """Test unique_id uses group_id."""
        group = _make_mock_group(group_id=5)
        router = _make_mock_router()
        light = HelvarGroupLight(group, router, None, 100)
        assert light.unique_id == "helvar-group-5"

    def test_name_from_helvar(self):
        """Test name comes from the Helvar group name."""
        group = _make_mock_group(name="Group 5")
        router = _make_mock_router()
        light = HelvarGroupLight(group, router, None, 100)
        assert light.name == "Group 5"

    def test_name_custom(self):
        """Test custom group name from Helvar."""
        group = _make_mock_group(name="Reception Lights")
        router = _make_mock_router()
        light = HelvarGroupLight(group, router, None, 100)
        assert light.name == "Reception Lights"

    def test_is_on_when_any_member_on(self):
        """Test is_on returns True when any member has load_level > 0."""
        addr1 = "1.2.3.4"
        addr2 = "1.2.3.5"
        dev1 = _make_mock_device(address=addr1, load_level=50.0)
        dev2 = _make_mock_device(address=addr2, load_level=0.0)
        group = _make_mock_group(device_addresses=[addr1, addr2])
        router = _make_mock_router(devices_dict={addr1: dev1, addr2: dev2})

        light = HelvarGroupLight(group, router, None, 100)
        assert light.is_on is True

    def test_is_on_when_all_members_off(self):
        """Test is_on returns False when all members have load_level 0."""
        addr1 = "1.2.3.4"
        addr2 = "1.2.3.5"
        dev1 = _make_mock_device(address=addr1, load_level=0.0, brightness=0)
        dev2 = _make_mock_device(address=addr2, load_level=0.0, brightness=0)
        group = _make_mock_group(device_addresses=[addr1, addr2])
        router = _make_mock_router(devices_dict={addr1: dev1, addr2: dev2})

        light = HelvarGroupLight(group, router, None, 100)
        assert light.is_on is False

    def test_brightness_averages_on_members(self):
        """Test brightness averages only members that are on."""
        addr1 = "1.2.3.4"
        addr2 = "1.2.3.5"
        addr3 = "1.2.3.6"
        # brightness 200 (on), brightness 100 (on), brightness 0 (off)
        dev1 = _make_mock_device(address=addr1, brightness=200, load_level=78.0)
        dev2 = _make_mock_device(address=addr2, brightness=100, load_level=39.0)
        dev3 = _make_mock_device(address=addr3, brightness=0, load_level=0.0)
        group = _make_mock_group(device_addresses=[addr1, addr2, addr3])
        router = _make_mock_router(devices_dict={addr1: dev1, addr2: dev2, addr3: dev3})

        light = HelvarGroupLight(group, router, None, 100)
        # Average of 200 and 100 = 150
        assert light._attr_brightness == 150

    def test_brightness_zero_when_all_off(self):
        """Test brightness is 0 when all members are off."""
        addr1 = "1.2.3.4"
        dev1 = _make_mock_device(address=addr1, brightness=0, load_level=0.0)
        group = _make_mock_group(device_addresses=[addr1])
        router = _make_mock_router(devices_dict={addr1: dev1})

        light = HelvarGroupLight(group, router, None, 100)
        assert light._attr_brightness == 0

    def test_color_mode_brightness_for_non_color_devices(self):
        """Test color mode defaults to BRIGHTNESS for non-color devices."""
        addr1 = "1.2.3.4"
        dev1 = _make_mock_device(address=addr1, is_color=False, is_load=True)
        group = _make_mock_group(device_addresses=[addr1])
        router = _make_mock_router(devices_dict={addr1: dev1})

        light = HelvarGroupLight(group, router, None, 100)
        assert light._attr_color_mode == ColorMode.BRIGHTNESS
        assert ColorMode.BRIGHTNESS in light._attr_supported_color_modes

    def test_color_mode_xy_when_configured(self):
        """Test color mode XY for color devices with XY config."""
        addr1 = "1.2.3.4"
        dev1 = _make_mock_device(address=addr1, is_color=True, is_load=True)
        group = _make_mock_group(device_addresses=[addr1])
        router = _make_mock_router(devices_dict={addr1: dev1})

        light = HelvarGroupLight(group, router, "xy", 100)
        assert light._attr_color_mode == ColorMode.XY
        assert ColorMode.XY in light._attr_supported_color_modes

    def test_color_mode_color_temp_when_configured(self):
        """Test color mode COLOR_TEMP for color devices with mireds config."""
        addr1 = "1.2.3.4"
        dev1 = _make_mock_device(address=addr1, is_color=True, is_load=True)
        group = _make_mock_group(device_addresses=[addr1])
        router = _make_mock_router(devices_dict={addr1: dev1})

        light = HelvarGroupLight(group, router, "mireds", 100)
        assert light._attr_color_mode == ColorMode.COLOR_TEMP
        assert ColorMode.COLOR_TEMP in light._attr_supported_color_modes

    def test_onoff_mode_when_no_load_devices(self):
        """Test ONOFF mode when no devices support dimming."""
        addr1 = "1.2.3.4"
        dev1 = _make_mock_device(address=addr1, is_color=False, is_load=False)
        group = _make_mock_group(device_addresses=[addr1])
        router = _make_mock_router(devices_dict={addr1: dev1})

        light = HelvarGroupLight(group, router, None, 100)
        assert light._attr_color_mode == ColorMode.ONOFF
        assert ColorMode.ONOFF in light._attr_supported_color_modes

    def test_should_poll_false(self):
        """Test that polling is disabled."""
        group = _make_mock_group()
        router = _make_mock_router()
        light = HelvarGroupLight(group, router, None, 100)
        assert light.should_poll is False

    def test_has_entity_name(self):
        """Test that has_entity_name is set."""
        group = _make_mock_group()
        router = _make_mock_router()
        light = HelvarGroupLight(group, router, None, 100)
        assert light._attr_has_entity_name is True

    def test_icon(self):
        """Test group icon."""
        group = _make_mock_group()
        router = _make_mock_router()
        light = HelvarGroupLight(group, router, None, 100)
        assert light._attr_icon == "mdi:lightbulb-group"

    def test_missing_member_devices_skipped(self):
        """Test that missing devices in router.api.devices are skipped."""
        addr1 = "1.2.3.4"
        addr_missing = "9.9.9.9"
        dev1 = _make_mock_device(address=addr1)
        group = _make_mock_group(device_addresses=[addr1, addr_missing])
        router = _make_mock_router(devices_dict={addr1: dev1})

        light = HelvarGroupLight(group, router, None, 100)
        members = light._get_member_devices()
        assert len(members) == 1
        assert members[0] is dev1


class TestHelvarGroupLightControl:
    """Test HelvarGroupLight turn on/off commands."""

    @pytest.mark.asyncio
    async def test_turn_on_with_brightness(self):
        """Test turning on with brightness sends group level command."""
        addr1 = "1.2.3.4"
        dev1 = _make_mock_device(address=addr1, brightness=0, load_level=0.0)
        group = _make_mock_group(device_addresses=[addr1])
        router = _make_mock_router(devices_dict={addr1: dev1})

        light = HelvarGroupLight(group, router, None, 100)
        await light.async_turn_on(**{ATTR_BRIGHTNESS: 200})

        router.api.groups.set_group_level.assert_called_once_with(
            group.group_id,
            f"{((200 / 255) * 100):.1f}",
            fade_time=100,
        )

    @pytest.mark.asyncio
    async def test_turn_on_without_brightness_defaults_to_255(self):
        """Test turning on without brightness defaults to 255."""
        addr1 = "1.2.3.4"
        dev1 = _make_mock_device(address=addr1, brightness=0, load_level=0.0)
        group = _make_mock_group(device_addresses=[addr1])
        router = _make_mock_router(devices_dict={addr1: dev1})

        light = HelvarGroupLight(group, router, None, 100)
        await light.async_turn_on()

        router.api.groups.set_group_level.assert_called_once_with(
            group.group_id,
            "100.0",
            fade_time=100,
        )

    @pytest.mark.asyncio
    async def test_turn_off(self):
        """Test turning off sends group level 0."""
        addr1 = "1.2.3.4"
        dev1 = _make_mock_device(address=addr1)
        group = _make_mock_group(device_addresses=[addr1])
        router = _make_mock_router(devices_dict={addr1: dev1})

        light = HelvarGroupLight(group, router, None, 100)
        await light.async_turn_off()

        router.api.groups.set_group_level.assert_called_once_with(
            group.group_id,
            "0",
            fade_time=100,
        )


class TestHelvarGroupLightSubscriptions:
    """Test HelvarGroupLight subscription callbacks."""

    @pytest.mark.asyncio
    async def test_subscribes_to_member_devices(self):
        """Test that async_added_to_hass subscribes to each member device."""
        addr1 = "1.2.3.4"
        addr2 = "1.2.3.5"
        dev1 = _make_mock_device(address=addr1)
        dev2 = _make_mock_device(address=addr2)
        group = _make_mock_group(device_addresses=[addr1, addr2])
        router = _make_mock_router(devices_dict={addr1: dev1, addr2: dev2})

        light = HelvarGroupLight(group, router, None, 100)
        light.hass = Mock()
        light.async_write_ha_state = Mock()

        await light.async_added_to_hass()

        # Should subscribe to both member devices
        assert router.api.devices.register_subscription.call_count == 2
        call_addrs = [
            call[0][0]
            for call in router.api.devices.register_subscription.call_args_list
        ]
        assert addr1 in call_addrs
        assert addr2 in call_addrs

    @pytest.mark.asyncio
    async def test_subscribes_to_group(self):
        """Test that async_added_to_hass subscribes to group updates."""
        group = _make_mock_group(group_id=5)
        router = _make_mock_router()

        light = HelvarGroupLight(group, router, None, 100)
        light.hass = Mock()
        light.async_write_ha_state = Mock()

        await light.async_added_to_hass()

        router.api.groups.register_subscription.assert_called_once()
        call_args = router.api.groups.register_subscription.call_args[0]
        assert call_args[0] == 5  # group_id

    @pytest.mark.asyncio
    async def test_member_callback_updates_state(self):
        """Test member device callback triggers state update."""
        addr1 = "1.2.3.4"
        dev1 = _make_mock_device(address=addr1)
        group = _make_mock_group(device_addresses=[addr1])
        router = _make_mock_router(devices_dict={addr1: dev1})

        light = HelvarGroupLight(group, router, None, 100)
        light.hass = Mock()
        light.async_write_ha_state = Mock()

        await light.async_added_to_hass()

        # Get the member callback that was registered
        member_callback = router.api.devices.register_subscription.call_args[0][1]

        # Call it
        await member_callback(dev1)

        light.async_write_ha_state.assert_called()

    @pytest.mark.asyncio
    async def test_group_callback_updates_state(self):
        """Test group callback triggers state update."""
        group = _make_mock_group(group_id=5)
        router = _make_mock_router()

        light = HelvarGroupLight(group, router, None, 100)
        light.hass = Mock()
        light.async_write_ha_state = Mock()

        await light.async_added_to_hass()

        # Get the group callback that was registered
        group_callback = router.api.groups.register_subscription.call_args[0][1]

        # Call it
        await group_callback()

        light.async_write_ha_state.assert_called()


class TestAsyncSetupEntry:
    """Test the group async_setup_entry function."""

    @pytest.mark.asyncio
    async def test_creates_group_entities(self):
        """Test async_setup_entry creates HelvarGroupLight for each group."""
        addr1 = "1.2.3.4"
        dev1 = _make_mock_device(address=addr1)
        group1 = _make_mock_group(group_id=1, name="Group 1", device_addresses=[addr1])
        group2 = _make_mock_group(group_id=2, name="Group 2", device_addresses=[addr1])

        router = _make_mock_router(devices_dict={addr1: dev1})
        router.api.groups.groups = {1: group1, 2: group2}

        mock_hass = Mock()
        mock_hass.data = {HELVAR_DOMAIN: {"test_entry": router}}

        mock_config_entry = Mock()
        mock_config_entry.entry_id = "test_entry"
        mock_config_entry.data = {}
        mock_config_entry.options = {}

        mock_add_entities = Mock()

        await async_setup_entry(mock_hass, mock_config_entry, mock_add_entities)

        mock_add_entities.assert_called_once()
        entities = mock_add_entities.call_args[0][0]
        assert len(entities) == 2
        assert all(isinstance(e, HelvarGroupLight) for e in entities)

    @pytest.mark.asyncio
    async def test_group_names_from_helvar(self):
        """Test that group entities use names from the Helvar router."""
        addr1 = "1.2.3.4"
        dev1 = _make_mock_device(address=addr1)
        group1 = _make_mock_group(
            group_id=5, name="Reception Lights", device_addresses=[addr1]
        )

        router = _make_mock_router(devices_dict={addr1: dev1})
        router.api.groups.groups = {5: group1}

        mock_hass = Mock()
        mock_hass.data = {HELVAR_DOMAIN: {"test_entry": router}}

        mock_config_entry = Mock()
        mock_config_entry.entry_id = "test_entry"
        mock_config_entry.data = {}
        mock_config_entry.options = {}

        mock_add_entities = Mock()

        await async_setup_entry(mock_hass, mock_config_entry, mock_add_entities)

        entity = mock_add_entities.call_args[0][0][0]
        assert entity.name == "Reception Lights"

    @pytest.mark.asyncio
    async def test_no_groups(self):
        """Test async_setup_entry with no groups."""
        router = _make_mock_router()
        router.api.groups.groups = {}

        mock_hass = Mock()
        mock_hass.data = {HELVAR_DOMAIN: {"test_entry": router}}

        mock_config_entry = Mock()
        mock_config_entry.entry_id = "test_entry"
        mock_config_entry.data = {}
        mock_config_entry.options = {}

        mock_add_entities = Mock()

        await async_setup_entry(mock_hass, mock_config_entry, mock_add_entities)

        entities = mock_add_entities.call_args[0][0]
        assert len(entities) == 0
