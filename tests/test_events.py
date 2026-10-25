"""Contract tests for the shared parking event payload and vocabulary."""

from dataclasses import FrozenInstanceError, fields, is_dataclass

import pytest

from core import events


def test_parking_event_is_frozen() -> None:
    event = events.ParkingEvent(type="VEHICLE_CREATED", timestamp=12.5)

    assert is_dataclass(event)
    assert event.__dataclass_params__.frozen
    with pytest.raises(FrozenInstanceError):
        event.type = "VEHICLE_FINISHED"
    assert event.type == "VEHICLE_CREATED"


def test_parking_event_adds_optional_fields_without_changing_positional_contract() -> None:
    event_fields = fields(events.ParkingEvent)

    assert [(field.name, field.type) for field in event_fields] == [
        ("type", str),
        ("timestamp", float),
        ("vehicle_id", int | None),
        ("space_id", int | None),
        ("waiting_time", float | None),
        ("plate", str | None),
        ("authorized_space_id", int | None),
        ("reason", str | None),
    ]
    assert [field.default for field in event_fields[2:]] == [None] * 6

    minimal = events.ParkingEvent(type="VEHICLE_CREATED", timestamp=12.5)
    assert (minimal.vehicle_id, minimal.space_id, minimal.waiting_time,
            minimal.plate, minimal.authorized_space_id, minimal.reason) == (
        None,
        None,
        None,
        None,
        None,
        None,
    )
    positional = events.ParkingEvent("VEHICLE_ENTERED", 13.0, 7, 2, 0.25)
    assert (positional.vehicle_id, positional.space_id, positional.waiting_time) == (7, 2, 0.25)
    entered = events.ParkingEvent(
        type="VEHICLE_ENTERED",
        timestamp=13.0,
        vehicle_id=7,
        space_id=2,
        waiting_time=0.25,
    )
    assert (entered.vehicle_id, entered.space_id, entered.waiting_time) == (
        7,
        2,
        0.25,
    )


def test_only_approved_event_constants_are_defined() -> None:
    vehicle_types = {
        "VEHICLE_CREATED",
        "VEHICLE_WAITING",
        "VEHICLE_ENTERED",
        "VEHICLE_EXITED",
        "VEHICLE_FINISHED",
        "VEHICLE_REJECTED",
        "VEHICLE_CANCELLED",
    }
    simulator_types = {"SIMULATION_STARTED", "SIMULATION_FINISHED"}
    approved_types = vehicle_types | simulator_types

    assert {
        name: value
        for name, value in vars(events).items()
        if name.isupper() and not name.startswith("_")
    } == {name: name for name in approved_types}
    assert all(name.startswith("VEHICLE_") for name in vehicle_types)
    assert vehicle_types.isdisjoint(simulator_types)
    assert events.VEHICLE_CANCELLED in approved_types
