"""Tests for the EUHOMY CF008 car fridge (xbx/pxzopdhy) descriptor.

The fridge keeps separate °C (112/114) and °F (117/119) data point pairs and
only updates the pair DP 105 selects, so the climate entity has to follow
DP 105 for reads, writes, the reported unit and the set-point range.
"""

# pylint: disable=protected-access
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.climate.const import HVACAction, HVACMode
from homeassistant.const import UnitOfElectricPotential, UnitOfTemperature
from homeassistant.core import HomeAssistant

from custom_components.tuya_ble import climate, select, sensor
from custom_components.tuya_ble.device_registry import (
    get_mapped_dp_ids,
    get_registry,
)
from custom_components.tuya_ble.devices import (
    TuyaBLECoordinator,
    TuyaBLEProductInfo,
)
from custom_components.tuya_ble.tuya_ble import (
    TuyaBLEDataPointType,
    TuyaBLEDevice,
)
from tests.conftest import add_dp, build_context

CATEGORY = "xbx"
PRODUCT_ID = "pxzopdhy"

POWER_DP = 101
MODE_DP = 103
BATTERY_PROTECTION_DP = 104
UNIT_DP = 105
CURRENT_C_DP = 112
TARGET_C_DP = 114
CURRENT_F_DP = 117
TARGET_F_DP = 119
VOLTAGE_DP = 122

CELSIUS = 0
FAHRENHEIT = 1


def _products(platform_mapping: Mapping[str, Any]) -> list[Any]:
    """Return a platform's mappings for the fridge."""
    products = platform_mapping[CATEGORY].products
    assert products is not None
    return list(products[PRODUCT_ID])


def _climate(
    hass: HomeAssistant,
    device: TuyaBLEDevice,
    coordinator: TuyaBLECoordinator,
    product: TuyaBLEProductInfo,
) -> climate.TuyaBLEClimate:
    """Build the fridge climate entity from its registry mapping."""
    (mapping,) = _products(climate.mapping)
    entity = climate.TuyaBLEClimate(hass, coordinator, device, product, mapping)
    entity.hass = hass
    return entity


async def _push(
    hass: HomeAssistant,
    coordinator: TuyaBLECoordinator,
) -> None:
    """Deliver a coordinator update and let it settle."""
    coordinator.async_set_updated_data({})
    await hass.async_block_till_done()


def test_descriptor_registered() -> None:
    """The product is in the registry under its own name and brand."""
    entities = get_registry().get(CATEGORY, PRODUCT_ID)
    assert entities is not None
    assert entities.manufacturer == "EUHOMY"
    assert entities.dp_id_for("select", "temperature_unit") == UNIT_DP


def test_unknown_dps_stay_unmapped() -> None:
    """Only the confirmed data points are mapped; 102, 123 and 124 are not."""
    assert get_mapped_dp_ids(CATEGORY, PRODUCT_ID) == frozenset(
        {
            POWER_DP,
            MODE_DP,
            BATTERY_PROTECTION_DP,
            UNIT_DP,
            CURRENT_C_DP,
            TARGET_C_DP,
            CURRENT_F_DP,
            TARGET_F_DP,
            VOLTAGE_DP,
        }
    )


async def test_climate_defaults_before_any_report(hass: HomeAssistant) -> None:
    """With nothing reported the fridge is a °C cooler with an unknown reading."""
    device, coordinator, product = build_context(hass)
    entity = _climate(hass, device, coordinator, product)
    assert entity.hvac_modes == [HVACMode.OFF, HVACMode.COOL]
    assert entity.hvac_mode == HVACMode.COOL
    assert entity.hvac_action == HVACAction.COOLING
    assert entity.temperature_unit == UnitOfTemperature.CELSIUS
    assert (entity.min_temp, entity.max_temp) == (-20, 20)
    await entity.async_added_to_hass()
    await _push(hass, coordinator)
    assert entity.current_temperature is None
    assert entity.target_temperature is None


async def test_climate_reads_fahrenheit_pair(hass: HomeAssistant) -> None:
    """DP 105 = °F reads 117/119 and reports °F with the °F range."""
    device, coordinator, product = build_context(hass)
    entity = _climate(hass, device, coordinator, product)
    await entity.async_added_to_hass()
    add_dp(device, POWER_DP, TuyaBLEDataPointType.DT_BOOL, True)
    add_dp(device, UNIT_DP, TuyaBLEDataPointType.DT_ENUM, FAHRENHEIT)
    add_dp(device, CURRENT_F_DP, TuyaBLEDataPointType.DT_VALUE, 41)
    add_dp(device, TARGET_F_DP, TuyaBLEDataPointType.DT_VALUE, 32)
    await _push(hass, coordinator)
    assert entity.temperature_unit == UnitOfTemperature.FAHRENHEIT
    assert (entity.min_temp, entity.max_temp) == (-4, 68)
    assert entity.current_temperature == 41
    assert entity.target_temperature == 32
    assert entity.hvac_mode == HVACMode.COOL
    assert entity.hvac_action == HVACAction.COOLING


async def test_climate_switch_to_celsius_without_celsius_pair(
    hass: HomeAssistant,
) -> None:
    """Switching to °C before 112/114 arrive shows unknown, not stale °F values."""
    device, coordinator, product = build_context(hass)
    entity = _climate(hass, device, coordinator, product)
    await entity.async_added_to_hass()
    add_dp(device, UNIT_DP, TuyaBLEDataPointType.DT_ENUM, FAHRENHEIT)
    add_dp(device, CURRENT_F_DP, TuyaBLEDataPointType.DT_VALUE, 41)
    add_dp(device, TARGET_F_DP, TuyaBLEDataPointType.DT_VALUE, 32)
    await _push(hass, coordinator)

    add_dp(device, UNIT_DP, TuyaBLEDataPointType.DT_ENUM, CELSIUS)
    await _push(hass, coordinator)
    assert entity.temperature_unit == UnitOfTemperature.CELSIUS
    assert (entity.min_temp, entity.max_temp) == (-20, 20)
    assert entity.current_temperature is None
    assert entity.target_temperature is None
    assert entity.hvac_action == HVACAction.COOLING

    add_dp(device, CURRENT_C_DP, TuyaBLEDataPointType.DT_VALUE, 5)
    add_dp(device, TARGET_C_DP, TuyaBLEDataPointType.DT_VALUE, 0)
    await _push(hass, coordinator)
    assert entity.current_temperature == 5
    assert entity.target_temperature == 0


async def test_climate_ignores_stale_inactive_pair(hass: HomeAssistant) -> None:
    """In °C the stale °F pair never leaks into the reading, and vice versa."""
    device, coordinator, product = build_context(hass)
    entity = _climate(hass, device, coordinator, product)
    await entity.async_added_to_hass()
    add_dp(device, UNIT_DP, TuyaBLEDataPointType.DT_ENUM, CELSIUS)
    add_dp(device, CURRENT_C_DP, TuyaBLEDataPointType.DT_VALUE, -2)
    add_dp(device, TARGET_C_DP, TuyaBLEDataPointType.DT_VALUE, -5)
    add_dp(device, CURRENT_F_DP, TuyaBLEDataPointType.DT_VALUE, 50)
    add_dp(device, TARGET_F_DP, TuyaBLEDataPointType.DT_VALUE, 45)
    await _push(hass, coordinator)
    assert entity.current_temperature == -2
    assert entity.target_temperature == -5

    add_dp(device, UNIT_DP, TuyaBLEDataPointType.DT_ENUM, FAHRENHEIT)
    await _push(hass, coordinator)
    assert entity.current_temperature == 50
    assert entity.target_temperature == 45


async def test_climate_idle_at_set_point(hass: HomeAssistant) -> None:
    """A fridge at or below its set point is idle, not cooling."""
    device, coordinator, product = build_context(hass)
    entity = _climate(hass, device, coordinator, product)
    await entity.async_added_to_hass()
    add_dp(device, POWER_DP, TuyaBLEDataPointType.DT_BOOL, True)
    add_dp(device, UNIT_DP, TuyaBLEDataPointType.DT_ENUM, CELSIUS)
    add_dp(device, CURRENT_C_DP, TuyaBLEDataPointType.DT_VALUE, 3)
    add_dp(device, TARGET_C_DP, TuyaBLEDataPointType.DT_VALUE, 4)
    await _push(hass, coordinator)
    assert entity.hvac_action == HVACAction.IDLE


async def test_climate_power_off(hass: HomeAssistant) -> None:
    """DP 101 = false is HVAC off and idle."""
    device, coordinator, product = build_context(hass)
    entity = _climate(hass, device, coordinator, product)
    await entity.async_added_to_hass()
    add_dp(device, POWER_DP, TuyaBLEDataPointType.DT_BOOL, False)
    await _push(hass, coordinator)
    assert entity.hvac_mode == HVACMode.OFF
    assert entity.hvac_action == HVACAction.IDLE


async def test_climate_set_hvac_mode_writes_power(hass: HomeAssistant) -> None:
    """Off and cool write DP 101."""
    device, coordinator, product = build_context(hass)
    entity = _climate(hass, device, coordinator, product)
    await entity.async_set_hvac_mode(HVACMode.OFF)
    await hass.async_block_till_done()
    datapoint = device.datapoints[POWER_DP]
    assert datapoint is not None
    assert datapoint.value is False
    await entity.async_set_hvac_mode(HVACMode.COOL)
    await hass.async_block_till_done()
    assert datapoint.value is True


async def test_climate_set_temperature_celsius(hass: HomeAssistant) -> None:
    """In °C the set point is written to DP 114 and DP 119 is untouched."""
    device, coordinator, product = build_context(hass)
    entity = _climate(hass, device, coordinator, product)
    add_dp(device, UNIT_DP, TuyaBLEDataPointType.DT_ENUM, CELSIUS)
    await entity.async_set_temperature(temperature=-3.0)
    await hass.async_block_till_done()
    datapoint = device.datapoints[TARGET_C_DP]
    assert datapoint is not None
    assert datapoint.value == -3
    assert device.datapoints[TARGET_F_DP] is None


async def test_climate_set_temperature_fahrenheit(hass: HomeAssistant) -> None:
    """In °F the set point is written to DP 119, rounded to a whole degree."""
    device, coordinator, product = build_context(hass)
    entity = _climate(hass, device, coordinator, product)
    add_dp(device, UNIT_DP, TuyaBLEDataPointType.DT_ENUM, FAHRENHEIT)
    await entity.async_set_temperature(temperature=35.6)
    await hass.async_block_till_done()
    datapoint = device.datapoints[TARGET_F_DP]
    assert datapoint is not None
    assert datapoint.value == 36
    assert device.datapoints[TARGET_C_DP] is None


def _select(
    hass: HomeAssistant,
    device: TuyaBLEDevice,
    coordinator: TuyaBLECoordinator,
    product: TuyaBLEProductInfo,
    dp_id: int,
) -> select.TuyaBLESelect:
    """Build one of the fridge's select entities by data point."""
    (mapping,) = [
        item for item in _products(select.mapping) if item.dp_id == dp_id
    ]
    entity = select.TuyaBLESelect(hass, coordinator, device, product, mapping)
    entity.hass = hass
    return entity


async def test_selects_read_and_write_enums(hass: HomeAssistant) -> None:
    """Mode, battery protection and unit map enum codes to their options."""
    device, coordinator, product = build_context(hass)
    expected = {
        MODE_DP: (["Max", "Eco"], 1),
        BATTERY_PROTECTION_DP: (["Low", "Medium", "High"], 2),
        UNIT_DP: (["°C", "°F"], 1),
    }
    for dp_id, (options, code) in expected.items():
        entity = _select(hass, device, coordinator, product, dp_id)
        assert entity.options == options
        add_dp(device, dp_id, TuyaBLEDataPointType.DT_ENUM, code)
        assert entity.current_option == options[code]
        entity.select_option(options[0])
        await hass.async_block_till_done()
        datapoint = device.datapoints[dp_id]
        assert datapoint is not None
        assert datapoint.value == 0
        assert datapoint.dp_type == TuyaBLEDataPointType.DT_ENUM


async def test_supply_voltage_sensor(hass: HomeAssistant) -> None:
    """DP 122 is reported in tenths of a volt."""
    device, coordinator, product = build_context(hass)
    (mapping,) = _products(sensor.mapping)
    entity = sensor.TuyaBLESensor(hass, coordinator, device, product, mapping)
    entity.hass = hass
    await entity.async_added_to_hass()
    add_dp(device, VOLTAGE_DP, TuyaBLEDataPointType.DT_VALUE, 146)
    await _push(hass, coordinator)
    assert entity.native_value == 14.6
    assert entity.native_unit_of_measurement == UnitOfElectricPotential.VOLT
