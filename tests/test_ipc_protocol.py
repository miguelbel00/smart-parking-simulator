import math

import pytest

from core.events import ParkingEvent
from simulation.ipc_protocol import (
    MAX_DEPTH,
    MAX_MESSAGE_BYTES,
    MAX_ITEMS,
    ProtocolError,
    parking_event_from_message,
    parking_event_to_message,
    validate_message,
    validate_start_payload,
)


def config():
    return {"capacity": 5, "total_vehicles": 2, "min_arrival_time": 1,
            "max_arrival_time": 4, "min_parking_time": 3, "max_parking_time": 8}


def start_payload():
    return {"config": config(), "plate_sequence": ["ABC-1", "NO-1"], "authorization": {"vehicles": [
        {"plate": "ABC-1", "authorized": True, "space_id": 0},
        {"plate": "NO-1", "authorized": False, "space_id": None},
    ]}}


def start():
    return {"v": 1, "kind": "command", "run_id": "run-a",
            "name": "START", "request_id": "req-1", "payload": start_payload()}


@pytest.mark.parametrize("message", [
    start(),
    {"v": 1, "kind": "command", "run_id": "run-a", "name": "STOP", "request_id": "r-2"},
    {"v": 1, "kind": "command", "run_id": None, "name": "SHUTDOWN", "request_id": "r-3"},
    {"v": 1, "kind": "reply", "run_id": "run-a", "command": "START", "request_id": "r-1", "status": "accepted"},
    {"v": 1, "kind": "reply", "run_id": "run-a", "command": "STOP", "request_id": "r-2", "status": "rejected", "reason": "BUSY"},
    {"v": 1, "kind": "reply", "run_id": None, "command": "SHUTDOWN", "request_id": "r-3", "status": "accepted"},
    {"v": 1, "kind": "event", "run_id": "run-a", "seq": 0, "name": "SIMULATION_STARTED",
     "payload": {"type": "SIMULATION_STARTED", "timestamp": 1.0, "vehicle_id": None,
              "space_id": None, "waiting_time": None, "plate": None,
              "authorized_space_id": None, "reason": None}},
    {"v": 1, "kind": "audit", "run_id": None, "seq": 1, "name": "REQUEST", "timestamp": 2.0, "payload": {"action": "accepted"}},
    {"v": 1, "kind": "failure", "run_id": None, "name": "ENGINE_FAILED", "error": "WORKER_FAILED"},
])
def test_accepts_each_message_family(message):
    assert validate_message(message) is message


@pytest.mark.parametrize("change", [
    lambda m: m.update(v=2), lambda m: m.update(kind="unknown"),
    lambda m: m.update(extra=True), lambda m: m.update(request_id="bad id"),
    lambda m: m.update(name="BOGUS"), lambda m: m.update(status="pending"),
    lambda m: m.pop("request_id"),
])
def test_rejects_invalid_command_schema(change):
    message = start()
    change(message)
    with pytest.raises(ProtocolError):
        validate_message(message)


def test_stop_requires_run_and_start_requires_payload():
    with pytest.raises(ProtocolError):
        validate_message({"v": 1, "kind": "command", "run_id": None, "name": "STOP", "request_id": "x"})
    with pytest.raises(ProtocolError):
        validate_message({"v": 1, "kind": "command", "run_id": None, "name": "START", "request_id": "x"})
    message = start()
    message["run_id"] = None
    with pytest.raises(ProtocolError):
        validate_message(message)


def test_shutdown_must_be_engine_scoped():
    valid = {"v": 1, "kind": "command", "run_id": None,
             "name": "SHUTDOWN", "request_id": "shutdown-1"}
    assert validate_message(valid) is valid
    valid["run_id"] = "run-1"
    with pytest.raises(ProtocolError):
        validate_message(valid)


def test_replies_have_strict_optional_reason():
    with pytest.raises(ProtocolError):
        validate_message({"v": 1, "kind": "reply", "run_id": "run-x", "command": "START", "request_id": "x", "status": "accepted", "reason": "no"})
    with pytest.raises(ProtocolError):
        validate_message({"v": 1, "kind": "reply", "run_id": "run-x", "command": "START", "request_id": "x", "status": "rejected"})
    for code in ("worker failed", "X" * 65, "BAD-CODE", ""):
        with pytest.raises(ProtocolError):
            validate_message({"v": 1, "kind": "reply", "run_id": "run-x", "command": "START", "request_id": "x", "status": "rejected", "reason": code})


@pytest.mark.parametrize("error", ["worker failed", "X" * 65, "BAD-CODE", ""])
def test_failure_requires_stable_error_code(error):
    with pytest.raises(ProtocolError):
        validate_message({"v": 1, "kind": "failure", "run_id": None, "name": "ENGINE_FAILED", "error": error})


@pytest.mark.parametrize("value", [object(), math.inf, float("nan"), {1: "bad"}])
def test_rejects_objects_nonfinite_and_bad_keys(value):
    with pytest.raises(ProtocolError):
        validate_message({"v": 1, "kind": "audit", "run_id": None, "seq": 1,
                          "name": "ERROR", "timestamp": 1.0, "payload": {"bad": value}})


def test_rejects_cycles_and_size_or_depth_limits():
    cyclic = []
    cyclic.append(cyclic)
    with pytest.raises(ProtocolError):
        validate_message(cyclic)
    too_deep = nested = []
    for _ in range(MAX_DEPTH + 2):
        child = []
        nested.append(child)
        nested = child
    with pytest.raises(ProtocolError):
        validate_message(too_deep)
    huge = {"v": 1, "kind": "failure", "run_id": None, "name": "ENGINE_FAILED", "error": "x" * MAX_MESSAGE_BYTES}
    with pytest.raises(ProtocolError):
        validate_message(huge)


def test_message_byte_limit_is_aggregate():
    # This payload stays below the limit per field; the combined serialized
    # primitive content exceeds the bounded aggregate.
    message = {"v": 1, "kind": "audit", "run_id": None, "seq": 1,
               "name": "ERROR", "timestamp": 1.0,
               "payload": {"a": "x" * 32_700, "b": "y" * 32_700}}
    with pytest.raises(ProtocolError, match="message too large"):
        validate_message(message)


def test_max_items_boundary():
    from simulation.ipc_protocol import _primitive

    _primitive([None] * (MAX_ITEMS - 1))
    with pytest.raises(ProtocolError, match="maximum item count"):
        _primitive([None] * MAX_ITEMS)


@pytest.mark.parametrize("value", ["\ud800", ["x" * 20_000] * 4, 10 ** 70_000],
                         ids=["surrogate", "aggregate", "large-integer"])
def test_rejects_invalid_unicode_and_oversized_aggregate_or_integer(value):
    with pytest.raises(ProtocolError):
        validate_message({"v": 1, "kind": "audit", "run_id": None, "seq": 1,
                          "name": "ERROR", "timestamp": 1.0, "payload": {"value": value}})


def test_parking_event_round_trip_preserves_all_fields():
    original = ParkingEvent("VEHICLE_ENTERED", 12.5, 7, 3, 1.25, "ABC-1", 3, None)
    message = parking_event_to_message(original, "run-1", 9)
    assert parking_event_from_message(message) == original
    assert set(message["payload"]) == {"type", "timestamp", "vehicle_id", "space_id", "waiting_time", "plate", "authorized_space_id", "reason"}


def test_event_origin_is_optional_for_compatibility_and_validated_when_present():
    message = parking_event_to_message(ParkingEvent("SIMULATION_STARTED", 1.0), "run-1", 0)
    assert "origin" not in validate_message(message)
    message["origin"] = {"process_id": 123, "process_name": "parking-engine", "thread_name": "parking-admission"}
    assert validate_message(message)["origin"]["process_id"] == 123
    for invalid in (
        {"process_id": 0, "process_name": "p", "thread_name": "t"},
        {"process_id": 123, "process_name": "", "thread_name": "t"},
        {"process_id": 123, "process_name": "p"},
    ):
        message["origin"] = invalid
        with pytest.raises(ProtocolError):
            validate_message(message)


def test_audit_origin_metadata_is_optional_but_all_fields_are_required_when_present():
    message = {"v": 1, "kind": "audit", "run_id": "run-1", "seq": 0,
               "name": "REQUEST", "timestamp": 1.0, "payload": {"operation": "admission_attempt"}}
    assert validate_message(message) is message
    message["payload"].update(origin_process_id=123, origin_process_name="parking-engine",
                              origin_thread_name="simulation-producer")
    assert validate_message(message) is message
    for metadata in (
        {"origin_process_id": 123},
        {"origin_process_id": 0, "origin_process_name": "parking-engine",
         "origin_thread_name": "simulation-producer"},
        {"origin_process_id": 123, "origin_process_name": "", "origin_thread_name": "simulation-producer"},
    ):
        invalid = {**message, "payload": {"operation": "admission_attempt", **metadata}}
        with pytest.raises(ProtocolError):
            validate_message(invalid)


@pytest.mark.parametrize("event", [
    ParkingEvent("VEHICLE_CREATED", 1, 1, plate="A-1", authorized_space_id=2),
    ParkingEvent("VEHICLE_WAITING", 1, 1, plate="A-1", authorized_space_id=2),
    ParkingEvent("VEHICLE_ENTERED", 1, 1, 2, 0.0, "A-1", 2),
    ParkingEvent("VEHICLE_EXITED", 2, 1, 2, plate="A-1", authorized_space_id=2),
    ParkingEvent("VEHICLE_FINISHED", 2, 1, plate="A-1", authorized_space_id=2),
    ParkingEvent("VEHICLE_REJECTED", 1, None, plate=None, reason="INVALID_REQUEST"),
    ParkingEvent("VEHICLE_REJECTED", 1, 2, plate="A-1", authorized_space_id=2, reason="DUPLICATE_ACTIVE"),
    ParkingEvent("VEHICLE_CANCELLED", 1, 1, plate="A-1", authorized_space_id=2, reason="STOP_REQUESTED"),
    ParkingEvent("SIMULATION_STARTED", 1),
    ParkingEvent("SIMULATION_FINISHED", 2),
])
def test_accepts_producer_event_variants(event):
    assert parking_event_from_message(parking_event_to_message(event, "run-1", 0)) == event


@pytest.mark.parametrize("event", [
    ParkingEvent("VEHICLE_CREATED", 1, plate="A-1", authorized_space_id=2),
    ParkingEvent("VEHICLE_CREATED", 1, 1, plate="A-1"),
    ParkingEvent("VEHICLE_WAITING", 1, 1, 2, plate="A-1", authorized_space_id=2),
    ParkingEvent("VEHICLE_ENTERED", 1, 1, 2, None, "A-1", 2),
    ParkingEvent("VEHICLE_EXITED", 1, 1, plate="A-1", authorized_space_id=2),
    ParkingEvent("VEHICLE_FINISHED", 1, 1, plate="A-1", authorized_space_id=2, reason="oops"),
    ParkingEvent("VEHICLE_REJECTED", 1, 1, space_id=2, reason="INVALID_REQUEST"),
    ParkingEvent("VEHICLE_CANCELLED", 1, 1, plate="A-1", authorized_space_id=2, reason="OTHER"),
    ParkingEvent("SIMULATION_STARTED", 1, vehicle_id=1),
])
def test_rejects_invalid_event_semantics(event):
    with pytest.raises(ProtocolError):
        parking_event_to_message(event, "run-1", 0)


def test_rejects_unknown_event_and_bad_sequence():
    message = parking_event_to_message(ParkingEvent("SIMULATION_FINISHED", 3.0), "run-1", 0)
    message["seq"] = -1
    with pytest.raises(ProtocolError):
        validate_message(message)
    message["seq"] = 1
    message["name"] = "UNKNOWN"
    with pytest.raises(ProtocolError):
        validate_message(message)


def test_start_payload_validates_config_and_authorization_shape():
    assert validate_start_payload(start_payload()) == start_payload()
    for mutate in (
        lambda p: p["config"].update(capacity=0),
        lambda p: p["config"].update(max_arrival_time=-1),
        lambda p: p["config"].update(min_parking_time=9),
        lambda p: p["authorization"]["vehicles"][0].update(space_id=5),
        lambda p: p["authorization"]["vehicles"][0].update(extra="x"),
        lambda p: p["authorization"]["vehicles"].append({"plate": "abc-1", "authorized": False, "space_id": None}),
    ):
        payload = start_payload()
        mutate(payload)
        with pytest.raises(ProtocolError):
            validate_start_payload(payload)


def test_start_preserves_ordered_duplicate_plate_sequence_independent_of_total():
    payload = start_payload()
    payload["plate_sequence"] = ["NO-1", "ABC-1", "NO-1"]
    assert payload["config"]["total_vehicles"] == 2
    assert validate_start_payload(payload)["plate_sequence"] == ["NO-1", "ABC-1", "NO-1"]


def test_start_accepts_long_plate_within_message_bound():
    payload = start_payload()
    payload["authorization"]["vehicles"] = [
        {"plate": "A" * 1_000, "authorized": True, "space_id": 0}
    ]
    assert validate_start_payload(payload) is payload


def test_start_requires_run_scope_and_preserves_correlation_fields():
    message = start()
    assert validate_message(message)["request_id"] == "req-1"
    assert message["run_id"] == "run-a"


@pytest.mark.parametrize("command,run_id", [
    ("START", "run-a"), ("STOP", "run-a"), ("SHUTDOWN", None),
])
@pytest.mark.parametrize("status", ["accepted", "rejected"])
def test_reply_scope_is_structural_and_controller_correlates_commands(command, run_id, status):
    reply = {"v": 1, "kind": "reply", "run_id": run_id, "command": command,
             "request_id": "req-1", "status": status}
    if status == "rejected":
        reply["reason"] = "BUSY"
    assert validate_message(reply) is reply


@pytest.mark.parametrize("command,run_id", [
    ("START", None), ("STOP", None), ("SHUTDOWN", "run-a"),
])
def test_rejects_reply_with_wrong_run_id_scope(command, run_id):
    reply = {"v": 1, "kind": "reply", "run_id": run_id, "command": command,
             "request_id": "req-1", "status": "rejected", "reason": "BUSY"}
    with pytest.raises(ProtocolError):
        validate_message(reply)


def test_rejected_start_reply_retains_run_id_at_structural_level():
    reply = {"v": 1, "kind": "reply", "run_id": "run-a", "command": "START",
             "request_id": "req-1", "status": "rejected", "reason": "BUSY"}
    assert validate_message(reply) is reply


def test_reply_requires_known_command_and_valid_run_id():
    for change in (lambda m: m.update(command="BOGUS"),
                   lambda m: m.update(run_id="bad id"),
                   lambda m: m.pop("command")):
        reply = {"v": 1, "kind": "reply", "run_id": "run-a", "command": "START",
                 "request_id": "req-1", "status": "accepted"}
        change(reply)
        with pytest.raises(ProtocolError):
            validate_message(reply)


def test_event_run_id_is_preserved_in_both_conversion_directions():
    original = ParkingEvent("SIMULATION_STARTED", 1.0)
    message = parking_event_to_message(original, "run-a", 0)
    assert message["run_id"] == "run-a"
    restored = parking_event_from_message(message)
    rebuilt = parking_event_to_message(restored, message["run_id"], 0)
    assert rebuilt["run_id"] == message["run_id"]
