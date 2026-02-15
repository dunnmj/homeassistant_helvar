"""Tests for the Helvar light platform."""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode

from custom_components.helvar.light import HelvarLight, async_setup_entry
from custom_components.helvar.const import DOMAIN as HELVAR_DOMAIN


class TestHelvarLight:
    """Test the HelvarLight class."""

    def test_init(self, mock_device, mock_router):
        """Test HelvarLight initialization."""
        light = HelvarLight(mock_device, mock_router, None, 100)

        assert light.device == mock_device
        assert light.router == mock_router

    def test_unique_id(self, mock_device, mock_router):
        """Test unique_id property."""
        light = HelvarLight(mock_device, mock_router, None, 100)
        assert light.unique_id == "1.2.3.4-light"

    def test_name(self, mock_device, mock_router):
        """Test name property."""
        light = HelvarLight(mock_device, mock_router, None, 100)
        assert light.name == "Test Light"

    def test_brightness(self, mock_device, mock_router):
        """Test brightness property."""
        light = HelvarLight(mock_device, mock_router, None, 100)
        assert light.brightness == 128

    def test_is_on_when_brightness_greater_than_zero(self, mock_device, mock_router):
        """Test is_on returns True when brightness > 0."""
        mock_device.brightness = 100
        light = HelvarLight(mock_device, mock_router, None, 100)
        assert light.is_on is True

    def test_is_on_when_brightness_is_zero(self, mock_device, mock_router):
        """Test is_on returns False when brightness is 0."""
        mock_device.brightness = 0
        light = HelvarLight(mock_device, mock_router, None, 100)
        assert light.is_on is False

    def test_supported_color_modes(self, mock_device, mock_router):
        """Test supported_color_modes property."""
        mock_device.is_color = False
        light = HelvarLight(mock_device, mock_router, None, 100)
        assert light.supported_color_modes == {ColorMode.BRIGHTNESS}

    def test_color_mode(self, mock_device, mock_router):
        """Test color_mode property."""
        mock_device.is_color = False
        light = HelvarLight(mock_device, mock_router, None, 100)
        assert light.color_mode == ColorMode.BRIGHTNESS

    @pytest.mark.asyncio
    async def test_async_turn_on_with_brightness(self, mock_device, mock_router):
        """Test turning on the light with brightness."""
        light = HelvarLight(mock_device, mock_router, None, 100)

        await light.async_turn_on(**{ATTR_BRIGHTNESS: 200})

        mock_router.api.devices.set_device_brightness.assert_called_once_with(
            mock_device.address, 200, fade_time=100
        )

    @pytest.mark.asyncio
    async def test_async_turn_on_without_brightness(self, mock_device, mock_router):
        """Test turning on the light without brightness (defaults to 255)."""
        light = HelvarLight(mock_device, mock_router, None, 100)

        await light.async_turn_on()

        mock_router.api.devices.set_device_brightness.assert_called_once_with(
            mock_device.address, 255, fade_time=100
        )

    @pytest.mark.asyncio
    async def test_async_turn_off(self, mock_device, mock_router):
        """Test turning off the light."""
        light = HelvarLight(mock_device, mock_router, None, 100)

        await light.async_turn_off()

        mock_router.api.devices.set_device_brightness.assert_called_once_with(
            mock_device.address, 0, fade_time=100
        )

    @pytest.mark.asyncio
    async def test_subscription_callback(self, mock_device, mock_router):
        """Test that subscription callback triggers state update."""
        light = HelvarLight(mock_device, mock_router, None, 100)

        # Mock the hass and async_write_ha_state methods
        light.hass = Mock()
        light.async_write_ha_state = Mock()

        await light.async_added_to_hass()

        # Get the callback that was registered
        callback = mock_router.api.devices.register_subscription.call_args[0][1]

        # Call the callback
        await callback(mock_device)

        # Verify state update was triggered
        light.async_write_ha_state.assert_called_once()


class TestAsyncSetupEntry:
    """Test the async_setup_entry function."""

    @pytest.mark.asyncio
    async def test_async_setup_entry(
        self, mock_hass, mock_config_entry, mock_add_entities, mock_router
    ):
        """Test async_setup_entry sets up devices and then groups."""
        # Setup mock devices
        mock_device1 = Mock()
        mock_device1.address = "1.2.3.4"
        mock_device1.name = "Light 1"
        mock_device1.brightness = 100
        mock_device1.is_color = False

        mock_device2 = Mock()
        mock_device2.address = "1.2.3.5"
        mock_device2.name = "Light 2"
        mock_device2.brightness = 200
        mock_device2.is_color = False

        mock_router.api.devices.get_light_devices.return_value = [
            mock_device1,
            mock_device2,
        ]

        # Setup hass data
        mock_hass.data = {HELVAR_DOMAIN: {mock_config_entry.entry_id: mock_router}}
        mock_config_entry.data = {}
        mock_config_entry.options = {}

        await async_setup_entry(mock_hass, mock_config_entry, mock_add_entities)

        # Verify add_entities was called twice: once for devices, once for groups
        assert mock_add_entities.call_count == 2
        # First call is individual lights
        device_entities = mock_add_entities.call_args_list[0][0][0]
        assert len(device_entities) == 2
        # Second call is groups (empty in this case)
        group_entities = mock_add_entities.call_args_list[1][0][0]
        assert len(group_entities) == 0

    @pytest.mark.asyncio
    async def test_async_setup_entry_no_devices(
        self, mock_hass, mock_config_entry, mock_add_entities, mock_router
    ):
        """Test async_setup_entry with no devices."""
        # Setup empty device list
        mock_router.api.devices.get_light_devices.return_value = []

        # Setup hass data
        mock_hass.data = {HELVAR_DOMAIN: {mock_config_entry.entry_id: mock_router}}
        mock_config_entry.data = {}
        mock_config_entry.options = {}

        await async_setup_entry(mock_hass, mock_config_entry, mock_add_entities)

        # First call is individual lights (empty), second is groups (empty)
        assert mock_add_entities.call_count == 2
        assert len(mock_add_entities.call_args_list[0][0][0]) == 0
        assert len(mock_add_entities.call_args_list[1][0][0]) == 0


class TestHelvarLightIntegration:
    """Integration tests for HelvarLight."""

    @pytest.mark.asyncio
    async def test_full_light_lifecycle(self, mock_device, mock_router):
        """Test a complete light lifecycle."""
        # Start with light off
        mock_device.brightness = 0
        light = HelvarLight(mock_device, mock_router, None, 100)

        # Verify initial state
        assert light.is_on is False
        assert light.brightness == 0

        # Turn on with brightness
        await light.async_turn_on(**{ATTR_BRIGHTNESS: 150})
        mock_router.api.devices.set_device_brightness.assert_called_with(
            mock_device.address, 150, fade_time=100
        )

        # Simulate device brightness update
        mock_device.brightness = 150
        assert light.is_on is True
        assert light.brightness == 150

        # Turn off
        await light.async_turn_off()
        mock_router.api.devices.set_device_brightness.assert_called_with(
            mock_device.address, 0, fade_time=100
        )

        # Simulate device brightness update
        mock_device.brightness = 0
        assert light.is_on is False
        assert light.brightness == 0

    def test_light_properties_consistency(self, mock_device, mock_router):
        """Test that light properties are consistent."""
        mock_device.is_color = False
        light = HelvarLight(mock_device, mock_router, None, 100)

        # Test various brightness levels
        test_values = [0, 1, 127, 128, 254, 255]

        for brightness in test_values:
            mock_device.brightness = brightness
            assert light.brightness == brightness
            assert light.is_on == (brightness > 0)
            assert light.color_mode == ColorMode.BRIGHTNESS
            assert ColorMode.BRIGHTNESS in light.supported_color_modes
