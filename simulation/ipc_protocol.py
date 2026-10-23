"""Version 1, transport-neutral IPC messages made only from validated primitives.

Messages are dictionaries intended for a future transport; this module does not
create processes or provide transport. A command's accepted reply means the
request was accepted, not completed. SIMULATION_STARTED means start became
effective; SIMULATION_FINISHED means normal completion only. Each run has its
own run_id (engine-scoped messages use ``None``). Replies echo their command so
the validator can check structural scope. The controller must still correlate
the exact request_id and run_id across messages; this stateless validator does
not match replies to requests. Sequence numbers are
nonnegative publication labels, not enforced ordering or causality. Vehicle
terminal events precede normal finish, but a fatal crash may prevent
ENGINE_FAILED delivery. STOP requests a run stop; SHUTDOWN requests engine
shutdown.

Reply rejection reasons and failure errors are bounded stable error codes
(uppercase ASCII identifiers), never free-form prose or exception text.
"""

from __future__ import annotations

import math
import re
from typing import Any

from core.events import ParkingEvent

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 65_536
MAX_DEPTH = 16
MAX_ITEMS = 4_096
COMMANDS = frozenset({"START", "STOP", "SHUTDOWN"})
REPLIES = frozenset({"accepted", "rejected"})
EVENTS = frozenset({"VEHICLE_CREATED", "VEHICLE_WAITING", "VEHICLE_ENTERED", "VEHICLE_EXITED", "VEHICLE_FINISHED", "VEHICLE_REJECTED", "VEHICLE_CANCELLED", "SIMULATION_STARTED", "SIMULATION_FINISHED"})
AUDIT_NAMES = frozenset({"REQUEST", "VALIDATION", "ADMISSION", "WAIT", "ENTRY", "EXIT", "ERROR"})
FAILURES = frozenset({"ENGINE_FAILED"})
REJECTION_REASONS = frozenset({"UNKNOWN_PLATE", "NOT_AUTHORIZED", "DUPLICATE_ACTIVE", "LOT_CLOSED", "INVALID_REQUEST"})
EVENT_FIELDS = ("type", "timestamp", "vehicle_id", "space_id", "waiting_time", "plate", "authorized_space_id", "reason")
CONFIG_FIELDS = frozenset({"capacity", "total_vehicles", "min_arrival_time", "max_arrival_time", "min_parking_time", "max_parking_time"})
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class ProtocolError(ValueError):
    """Invalid protocol data; messages are bounded and omit input contents."""


def _fail(message: str) -> None:
    raise ProtocolError(message[:160])


def _identifier(value: Any, field: str, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or not _ID.fullmatch(value):
        _fail(f"invalid {field}")


def _primitive(value: Any, depth: int = 0, budget: list[int] | None = None, active: set[int] | None = None) -> None:
    if budget is None:
        budget, active = [MAX_ITEMS, 0], set()
    if depth > MAX_DEPTH:
        _fail("maximum nesting depth exceeded")
    budget[0] -= 1
    if budget[0] < 0:
        _fail("maximum item count exceeded")
    budget[1] += 8
    if budget[1] > MAX_MESSAGE_BYTES:
        _fail("message too large")
    if value is None or type(value) in (bool, int, str):
        if type(value) is str:
            try:
                size = len(value.encode("utf-8"))
            except UnicodeEncodeError:
                _fail("invalid Unicode string")
            budget[1] += size
        elif type(value) is int:
            budget[1] += max(1, (value.bit_length() + 2) // 3)
        if budget[1] > MAX_MESSAGE_BYTES:
            _fail("message too large")
        return
    if type(value) is float:
        if not math.isfinite(value):
            _fail("non-finite number")
        budget[1] += 24
        if budget[1] > MAX_MESSAGE_BYTES:
            _fail("message too large")
        return
    if type(value) not in (dict, list):
        _fail("only primitive dictionaries and lists are allowed")
    ident = id(value)
    if ident in active:
        _fail("cyclic structure")
    active.add(ident)
    try:
        if type(value) is dict:
            for key, item in value.items():
                if type(key) is not str:
                    _fail("dictionary keys must be strings")
                _primitive(key, depth + 1, budget, active)
                _primitive(item, depth + 1, budget, active)
        else:
            for item in value:
                _primitive(item, depth + 1, budget, active)
    finally:
        active.remove(ident)


def _schema(message: dict[str, Any], required: set[str], optional: set[str]) -> None:
    fields = set(message)
    if not required <= fields or fields - required - optional:
        _fail("missing or unknown message fields")


def validate_start_payload(payload: Any) -> dict[str, Any]:
    """Validate START config and authorization records without loading files."""
    _primitive(payload)
    if type(payload) is not dict or set(payload) != {"config", "authorization"}:
        _fail("invalid START payload")
    config, authorization = payload["config"], payload["authorization"]
    if type(config) is not dict or set(config) != CONFIG_FIELDS:
        _fail("invalid START config fields")
    for value in config.values():
        if type(value) is not int or value < 0:
            _fail("config values must be nonnegative integers")
    if config["capacity"] < 1 or config["total_vehicles"] < 1:
        _fail("capacity and total_vehicles must be positive")
    if config["min_arrival_time"] > config["max_arrival_time"] or config["min_parking_time"] > config["max_parking_time"]:
        _fail("invalid config range")
    if type(authorization) is not dict or set(authorization) != {"vehicles"} or type(authorization["vehicles"]) is not list:
        _fail("invalid authorization payload")
    plates: set[str] = set()
    for record in authorization["vehicles"]:
        if type(record) is not dict or set(record) != {"plate", "authorized", "space_id"}:
            _fail("invalid authorization record")
        plate, allowed, slot = record["plate"], record["authorized"], record["space_id"]
        if not isinstance(plate, str) or not plate.strip():
            _fail("invalid authorization plate")
        canonical = plate.strip().upper()
        if canonical in plates:
            _fail("duplicate authorization plate")
        plates.add(canonical)
        if type(allowed) is not bool:
            _fail("invalid authorization flag")
        if allowed and (type(slot) is not int or not 0 <= slot < config["capacity"]):
            _fail("invalid authorized space")
        if not allowed and slot is not None:
            _fail("unauthorized record must have null space")
    return payload


def validate_message(message: Any) -> dict[str, Any]:
    """Validate and return a protocol-v1 message dictionary."""
    _primitive(message)
    if type(message) is not dict:
        _fail("message must be a dictionary")
    if type(message.get("v")) is not int or message["v"] != PROTOCOL_VERSION:
        _fail("unsupported protocol version")
    kind = message.get("kind")
    common = {"v", "kind", "run_id"}
    if kind == "command":
        _schema(message, common | {"name", "request_id"}, {"payload"})
        if not isinstance(message["name"], str) or message["name"] not in COMMANDS:
            _fail("unknown command")
        _identifier(message["request_id"], "request_id")
        _identifier(message["run_id"], "run_id", nullable=True)
        if message["name"] == "START":
            if "payload" not in message:
                _fail("START requires payload")
            validate_start_payload(message["payload"])
            if message["run_id"] is None:
                _fail("START requires run_id")
        elif "payload" in message:
            _fail("command does not accept payload")
        elif message["name"] == "STOP" and message["run_id"] is None:
            _fail("STOP requires run_id")
        elif message["name"] == "SHUTDOWN" and message["run_id"] is not None:
            _fail("SHUTDOWN must be engine-scoped")
    elif kind == "reply":
        _schema(message, common | {"command", "request_id", "status"}, {"reason"})
        if not isinstance(message["command"], str) or message["command"] not in COMMANDS:
            _fail("unknown reply command")
        _identifier(message["request_id"], "request_id")
        _identifier(message["run_id"], "run_id", nullable=True)
        if message["command"] in {"START", "STOP"} and message["run_id"] is None:
            _fail("run-scoped reply requires run_id")
        if message["command"] == "SHUTDOWN" and message["run_id"] is not None:
            _fail("SHUTDOWN reply must be engine-scoped")
        if not isinstance(message["status"], str) or message["status"] not in REPLIES:
            _fail("unknown reply status")
        if message["status"] == "rejected":
            if not isinstance(message.get("reason"), str) or not _ERROR_CODE.fullmatch(message["reason"]):
                _fail("rejected reply requires a stable error code")
        elif "reason" in message:
            _fail("accepted reply cannot have reason")
    elif kind == "event":
        _schema(message, common | {"seq", "name", "payload"}, set())
        _identifier(message["run_id"], "run_id")
        if type(message["seq"]) is not int or message["seq"] < 0:
            _fail("invalid event sequence")
        if not isinstance(message["name"], str) or message["name"] not in EVENTS:
            _fail("unknown event")
        _validate_event_data(message["payload"], message["name"])
    elif kind == "audit":
        _schema(message, common | {"seq", "name", "timestamp", "payload"}, set())
        _identifier(message["run_id"], "run_id", nullable=True)
        if type(message["seq"]) is not int or message["seq"] < 0 or type(message["timestamp"]) not in (int, float) or not math.isfinite(message["timestamp"]):
            _fail("invalid audit sequence or timestamp")
        if not isinstance(message["name"], str) or message["name"] not in AUDIT_NAMES or type(message["payload"]) is not dict:
            _fail("invalid audit record")
    elif kind == "failure":
        _schema(message, common | {"name", "error"}, {"request_id"})
        _identifier(message["run_id"], "run_id", nullable=True)
        if not isinstance(message["name"], str) or message["name"] not in FAILURES or not isinstance(message["error"], str) or not _ERROR_CODE.fullmatch(message["error"]):
            _fail("invalid failure record")
        if "request_id" in message:
            _identifier(message["request_id"], "request_id")
    else:
        _fail("unknown message kind")
    return message


def _validate_event_data(data: Any, name: str) -> None:
    if type(data) is not dict or set(data) != set(EVENT_FIELDS) or data["type"] != name:
        _fail("invalid event data fields or name")
    if type(data["timestamp"]) not in (int, float) or not math.isfinite(data["timestamp"]):
        _fail("invalid event timestamp")
    for field in ("vehicle_id", "space_id", "authorized_space_id"):
        value = data[field]
        if value is not None and (type(value) is not int or value < 0):
            _fail(f"invalid {field}")
    value = data["waiting_time"]
    if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
        _fail("invalid waiting_time")
    if data["plate"] is not None and not isinstance(data["plate"], str):
        _fail("invalid plate")
    reason = data["reason"]
    if reason is not None and (not isinstance(reason, str) or len(reason) > 160):
        _fail("invalid event reason")
    if name == "VEHICLE_REJECTED" and reason not in REJECTION_REASONS:
        _fail("invalid rejection reason")
    if name == "VEHICLE_CANCELLED" and reason != "STOP_REQUESTED":
        _fail("invalid cancellation reason")

    no_physical = {"space_id": None, "waiting_time": None}
    if name in {"SIMULATION_STARTED", "SIMULATION_FINISHED"}:
        required = {"vehicle_id": None, "space_id": None, "waiting_time": None,
                    "plate": None, "authorized_space_id": None, "reason": None}
    elif name in {"VEHICLE_CREATED", "VEHICLE_WAITING", "VEHICLE_FINISHED"}:
        required = {"vehicle_id": "present", "plate": "present",
                    "authorized_space_id": "present", **no_physical, "reason": None}
    elif name == "VEHICLE_ENTERED":
        required = {"vehicle_id": "present", "plate": "present",
                    "space_id": "present", "waiting_time": "present",
                    "authorized_space_id": "present", "reason": None}
    elif name == "VEHICLE_EXITED":
        required = {"vehicle_id": "present", "plate": "present",
                    "space_id": "present", "waiting_time": None,
                    "authorized_space_id": "present", "reason": None}
    elif name == "VEHICLE_CANCELLED":
        required = {"vehicle_id": "present", "plate": "present",
                    "authorized_space_id": "present", **no_physical,
                    "reason": "STOP_REQUESTED"}
    else:  # VEHICLE_REJECTED
        required = {"space_id": None, "waiting_time": None}
    for field, expectation in required.items():
        value = data[field]
        if expectation == "present" and value is None:
            _fail(f"{name} requires {field}")
        if expectation != "present" and value != expectation:
            _fail(f"invalid {name} {field}")
    if name in {"VEHICLE_CREATED", "VEHICLE_WAITING", "VEHICLE_ENTERED",
                "VEHICLE_EXITED", "VEHICLE_FINISHED", "VEHICLE_CANCELLED"}:
        if not data["plate"].strip():
            _fail(f"{name} requires plate")


def parking_event_to_message(event: ParkingEvent, run_id: str, seq: int) -> dict[str, Any]:
    """Serialize every ParkingEvent field into a validated event message."""
    if not isinstance(event, ParkingEvent):
        _fail("event must be ParkingEvent")
    data = {field: getattr(event, field) for field in EVENT_FIELDS}
    return validate_message({"v": PROTOCOL_VERSION, "kind": "event", "run_id": run_id, "seq": seq, "name": event.type, "payload": data})


def parking_event_from_message(message: Any) -> ParkingEvent:
    """Deserialize a validated event message without dropping event fields."""
    validated = validate_message(message)
    if validated["kind"] != "event":
        _fail("message is not an event")
    return ParkingEvent(**validated["payload"])
