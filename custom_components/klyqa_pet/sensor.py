"""Sensor platform for Klyqa Pet."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfMass,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from pyklyqa_pet import DeviceType

from . import KlyqaPetConfigEntry
from .const import (
    FOODY_BOWL_STATE,
    FOODY_ERROR_STATE,
    FOODY_FEEDING_STATE,
    FOODY_FOOD_BIN_STATE,
    FOODY_MANUAL_REPORT,
    FOODY_SCHEDULED_REPORT,
    PURIFIER_AQI_GRADES,
    WELLY_POWER_STATUS,
    WELLY_POWER_SUPPLY,
    WELLY_PUMP_STATUS,
)
from .coordinator import KlyqaDeviceCoordinator, KlyqaDeviceData
from .entity import KlyqaPetEntity, async_setup_platform_entities

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class KlyqaSensorEntityDescription(SensorEntityDescription):
    """Sensor description with a value extractor."""

    value_fn: Callable[[KlyqaDeviceData], StateType | datetime]


def _timestamp(seconds: int) -> datetime | None:
    return dt_util.utc_from_timestamp(seconds) if seconds > 0 else None


def _battery(level: int | None) -> int | None:
    return None if level is None or level < 0 else level


def _enum(mapping: dict[int, str], value: int) -> str | None:
    return mapping.get(value)


def _enum_description(
    key: str,
    mapping: dict[int, str],
    value_fn: Callable[[KlyqaDeviceData], int],
    entity_category: EntityCategory | None = None,
) -> KlyqaSensorEntityDescription:
    return KlyqaSensorEntityDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.ENUM,
        options=list(mapping.values()),
        entity_category=entity_category,
        value_fn=lambda data: _enum(mapping, value_fn(data)),
    )


COMMON_SENSORS: tuple[KlyqaSensorEntityDescription, ...] = (
    KlyqaSensorEntityDescription(
        key="wifi_rssi",
        translation_key="wifi_rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.state.wifi_rssi,
    ),
    KlyqaSensorEntityDescription(
        key="firmware_version",
        translation_key="firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.system_info.app_version or None,
    ),
    KlyqaSensorEntityDescription(
        key="sdk_version",
        translation_key="sdk_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.system_info.sdk_version or None,
    ),
    KlyqaSensorEntityDescription(
        key="last_boot",
        translation_key="last_boot",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: _timestamp(data.system_info.boot_time),
    ),
)

WELLY_SENSORS: tuple[KlyqaSensorEntityDescription, ...] = (
    KlyqaSensorEntityDescription(
        key="water_temperature",
        translation_key="water_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.welly.water_temperature,
    ),
    KlyqaSensorEntityDescription(
        key="clean_tank_volume",
        translation_key="clean_tank_volume",
        device_class=SensorDeviceClass.VOLUME,
        native_unit_of_measurement=UnitOfVolume.MILLILITERS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.welly.tank_clean,
    ),
    KlyqaSensorEntityDescription(
        key="sewage_tank_volume",
        translation_key="sewage_tank_volume",
        device_class=SensorDeviceClass.VOLUME,
        native_unit_of_measurement=UnitOfVolume.MILLILITERS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.welly.tank_sewage,
    ),
    KlyqaSensorEntityDescription(
        key="drinking_volume",
        translation_key="drinking_volume",
        device_class=SensorDeviceClass.VOLUME,
        native_unit_of_measurement=UnitOfVolume.MILLILITERS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.welly.drinking_volume,
    ),
    KlyqaSensorEntityDescription(
        key="total_consumption",
        translation_key="total_consumption",
        device_class=SensorDeviceClass.VOLUME,
        native_unit_of_measurement=UnitOfVolume.MILLILITERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.welly.total_consumption,
    ),
    KlyqaSensorEntityDescription(
        key="last_drinking",
        translation_key="last_drinking",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: _timestamp(data.welly.last_drinking_time),
    ),
    KlyqaSensorEntityDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _battery(data.welly.battery_level),
    ),
    KlyqaSensorEntityDescription(
        key="filter_life",
        translation_key="filter_life",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.welly.filter_life_remaining,
    ),
    _enum_description("pump_status", WELLY_PUMP_STATUS, lambda data: data.welly.pump_status),
    _enum_description(
        "power_status",
        WELLY_POWER_STATUS,
        lambda data: data.welly.power_status,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    _enum_description(
        "power_supply",
        WELLY_POWER_SUPPLY,
        lambda data: data.welly.power_supply,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    KlyqaSensorEntityDescription(
        key="descaling_status",
        translation_key="descaling_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.welly.descaling,
    ),
    KlyqaSensorEntityDescription(
        key="light_effect",
        translation_key="light_effect",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.welly.light_id,
    ),
)

FOODY_SENSORS: tuple[KlyqaSensorEntityDescription, ...] = (
    KlyqaSensorEntityDescription(
        key="bowl_remaining",
        translation_key="bowl_remaining",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.GRAMS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.foody.bowl_remaining,
    ),
    KlyqaSensorEntityDescription(
        key="realtime_weight",
        translation_key="realtime_weight",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.GRAMS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.foody.last_realtime_weight / 10,
    ),
    _enum_description("feeding_state", FOODY_FEEDING_STATE, lambda data: data.foody.feeding_state),
    _enum_description("bowl_state", FOODY_BOWL_STATE, lambda data: data.foody.bowl_state),
    _enum_description(
        "food_bin_state", FOODY_FOOD_BIN_STATE, lambda data: data.foody.food_bin_state
    ),
    _enum_description("error_state", FOODY_ERROR_STATE, lambda data: data.foody.error_state),
    _enum_description(
        "last_manual_feeding", FOODY_MANUAL_REPORT, lambda data: data.foody.last_manual_report
    ),
    KlyqaSensorEntityDescription(
        key="last_manual_portions",
        translation_key="last_manual_portions",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.foody.last_manual_portions,
    ),
    _enum_description(
        "last_scheduled_feeding",
        FOODY_SCHEDULED_REPORT,
        lambda data: data.foody.last_scheduled_report,
    ),
    KlyqaSensorEntityDescription(
        key="last_scheduled_portions",
        translation_key="last_scheduled_portions",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.foody.last_scheduled_portions,
    ),
    KlyqaSensorEntityDescription(
        key="next_feed_time",
        translation_key="next_feed_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda data: data.foody.next_feed_time,
    ),
    KlyqaSensorEntityDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _battery(data.foody.battery_level),
    ),
    KlyqaSensorEntityDescription(
        key="mcu_firmware_version",
        translation_key="mcu_firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.foody.mcu_sw_version,
    ),
)

PURIFIER_SENSORS: tuple[KlyqaSensorEntityDescription, ...] = (
    KlyqaSensorEntityDescription(
        key="pm25",
        device_class=SensorDeviceClass.PM25,
        native_unit_of_measurement=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.purifier.aqi_value,
    ),
    _enum_description("air_quality", PURIFIER_AQI_GRADES, lambda data: data.purifier.aqi_grade),
    KlyqaSensorEntityDescription(
        key="filter_remaining",
        translation_key="filter_remaining",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.purifier.filter_remaining_time,
    ),
    KlyqaSensorEntityDescription(
        key="filter_life",
        translation_key="filter_life",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda data: (
            round(100 * data.purifier.filter_remaining_time / data.purifier.filter_total_time, 1)
            if data.purifier.filter_total_time > 0
            else None
        ),
    ),
    KlyqaSensorEntityDescription(
        key="total_run_time",
        translation_key="total_run_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.purifier.total_run_time,
    ),
    KlyqaSensorEntityDescription(
        key="air_volume",
        translation_key="air_volume",
        device_class=SensorDeviceClass.VOLUME,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.purifier.air_volume,
    ),
    KlyqaSensorEntityDescription(
        key="pet_mode_time",
        translation_key="pet_mode_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.purifier.pet_mode_time,
    ),
)

SENSORS_BY_TYPE: dict[DeviceType, tuple[KlyqaSensorEntityDescription, ...]] = {
    DeviceType.WELLY: WELLY_SENSORS,
    DeviceType.FOODY: FOODY_SENSORS,
    DeviceType.AIRPURIFIER: PURIFIER_SENSORS,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KlyqaPetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors for all devices of the entry."""

    def _entities(coordinator: KlyqaDeviceCoordinator) -> list[KlyqaSensor]:
        descriptions = COMMON_SENSORS + SENSORS_BY_TYPE[coordinator.device_type]
        return [KlyqaSensor(coordinator, description) for description in descriptions]

    async_setup_platform_entities(entry, async_add_entities, _entities)


class KlyqaSensor(KlyqaPetEntity, SensorEntity):
    """A read-only value of a Klyqa device."""

    entity_description: KlyqaSensorEntityDescription

    @property
    def native_value(self) -> StateType | datetime:
        """Return the value extracted from the coordinator data."""
        return self.entity_description.value_fn(self.coordinator.data)
