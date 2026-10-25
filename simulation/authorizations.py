"""Load and validate the immutable vehicle authorization registry."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class Authorization:
    plate: str
    authorized: bool
    space_id: int | None


class AuthorizationConfigurationError(ValueError):
    """A sanitized authorization configuration error with stable context."""

    def __init__(self, code: str, context: str):
        self.code = code
        self.context = context
        super().__init__(f"{code}: {context}")


@dataclass(frozen=True, slots=True)
class AuthorizationRegistry:
    _records: Mapping[str, Authorization]

    def __post_init__(self) -> None:
        object.__setattr__(self, "_records", MappingProxyType(dict(self._records)))

    def lookup(self, plate: str) -> Authorization | None:
        """Return a registered record, or None when the plate is unknown."""
        if not isinstance(plate, str):
            return None
        return self._records.get(_canonical_plate(plate))

    @property
    def records(self) -> Mapping[str, Authorization]:
        return self._records


def load_authorizations(path: str | Path, capacity: int) -> AuthorizationRegistry:
    """Load a strict JSON authorization file for a parking lot capacity."""
    if type(capacity) is not int or capacity <= 0:
        raise AuthorizationConfigurationError("INVALID_CAPACITY", "capacity must be a positive integer")
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError, TypeError, ValueError):
        raise AuthorizationConfigurationError("FILE_READ_ERROR", "authorization file could not be read") from None
    try:
        data = json.loads(text, object_pairs_hook=_unique_object)
    except _DuplicateJSONKey:
        raise AuthorizationConfigurationError("INVALID_JSON", "JSON object contains a duplicate key") from None
    except json.JSONDecodeError as error:
        raise AuthorizationConfigurationError(
            "INVALID_JSON", f"invalid JSON syntax at line {error.lineno}, column {error.colno}"
        ) from None
    if not isinstance(data, dict) or set(data) != {"vehicles"}:
        raise AuthorizationConfigurationError("INVALID_SCHEMA", "root must contain only the vehicles array")
    vehicles = data["vehicles"]
    if not isinstance(vehicles, list):
        raise AuthorizationConfigurationError("INVALID_SCHEMA", "vehicles must be an array")

    records: dict[str, Authorization] = {}
    for index, entry in enumerate(vehicles):
        where = f"vehicles[{index}]"
        if not isinstance(entry, dict) or set(entry) != {"plate", "authorized", "space_id"}:
            raise AuthorizationConfigurationError("INVALID_RECORD", f"{where} must contain exactly plate, authorized, space_id")
        plate = entry["plate"]
        if not isinstance(plate, str) or not plate.strip():
            raise AuthorizationConfigurationError("INVALID_PLATE", f"{where}.plate must be a non-empty string")
        canonical = _canonical_plate(plate)
        if canonical in records:
            raise AuthorizationConfigurationError("DUPLICATE_PLATE", f"{where}.plate duplicates a registered plate")
        authorized = entry["authorized"]
        if type(authorized) is not bool:
            raise AuthorizationConfigurationError("INVALID_AUTHORIZATION", f"{where}.authorized must be a boolean")
        space_id = entry["space_id"]
        if authorized:
            if type(space_id) is not int or not 0 <= space_id < capacity:
                raise AuthorizationConfigurationError("INVALID_SPACE_ID", f"{where}.space_id must be an integer within capacity")
        elif space_id is not None:
            raise AuthorizationConfigurationError("INVALID_SPACE_ID", f"{where}.space_id must be null when unauthorized")
        records[canonical] = Authorization(canonical, authorized, space_id)
    return AuthorizationRegistry(records)


def _canonical_plate(plate: str) -> str:
    return plate.strip().upper()


class _DuplicateJSONKey(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKey
        result[key] = value
    return result
