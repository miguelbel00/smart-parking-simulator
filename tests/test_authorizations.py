import json

import pytest

from simulation.authorizations import (
    AuthorizationConfigurationError,
    load_authorizations,
)


def write_config(tmp_path, data):
    path = tmp_path / "authorizations.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def config(*records):
    return {"vehicles": list(records)}


def record(plate="abc-123", authorized=True, space_id=0):
    return {"plate": plate, "authorized": authorized, "space_id": space_id}


def test_loads_and_normalizes_records(tmp_path):
    registry = load_authorizations(write_config(tmp_path, config(record("  ab-12 "))), 2)
    assert registry.lookup("AB-12").plate == "AB-12"
    assert registry.lookup(" ab-12 ").space_id == 0


@pytest.mark.parametrize("plate", ["", "  ", None, 12])
def test_rejects_empty_or_non_string_plates(tmp_path, plate):
    with pytest.raises(AuthorizationConfigurationError) as error:
        load_authorizations(write_config(tmp_path, config(record(plate))), 2)
    assert error.value.code == "INVALID_PLATE"


def test_rejects_canonical_duplicate_plates(tmp_path):
    path = write_config(tmp_path, config(record("ab-12"), record(" AB-12 ")))
    with pytest.raises(AuthorizationConfigurationError) as error:
        load_authorizations(path, 2)
    assert error.value.code == "DUPLICATE_PLATE"


def test_distinguishes_unknown_and_registered_unauthorized(tmp_path):
    registry = load_authorizations(write_config(tmp_path, config(record("NO-ENTRY", False, None))), 2)
    assert registry.lookup("MISSING") is None
    assert registry.lookup("no-entry").authorized is False


def test_unauthorized_entry_requires_null_space(tmp_path):
    with pytest.raises(AuthorizationConfigurationError) as error:
        load_authorizations(write_config(tmp_path, config(record(authorized=False, space_id=0))), 2)
    assert error.value.code == "INVALID_SPACE_ID"


@pytest.mark.parametrize("space_id", [-1, 2, True, 1.0, "0"])
def test_rejects_invalid_authorized_space_ids(tmp_path, space_id):
    with pytest.raises(AuthorizationConfigurationError) as error:
        load_authorizations(write_config(tmp_path, config(record(space_id=space_id))), 2)
    assert error.value.code == "INVALID_SPACE_ID"


@pytest.mark.parametrize("authorized", [1, 0, "true", None])
def test_authorized_must_be_strict_boolean(tmp_path, authorized):
    with pytest.raises(AuthorizationConfigurationError) as error:
        load_authorizations(write_config(tmp_path, config(record(authorized=authorized))), 2)
    assert error.value.code == "INVALID_AUTHORIZATION"


@pytest.mark.parametrize("data", [None, [], {"other": []}, {"vehicles": None}, {"vehicles": {}}, {"vehicles": [None]}, {"vehicles": [{}]}, {"vehicles": [{"plate": "A", "authorized": True}]}, {"vehicles": [{"plate": "A", "authorized": True, "space_id": 0, "extra": 1}]}, {"vehicles": [], "extra": 1}])
def test_rejects_invalid_roots_schemas_and_records(tmp_path, data):
    with pytest.raises(AuthorizationConfigurationError):
        load_authorizations(write_config(tmp_path, data), 2)


def test_rejects_invalid_json_with_sanitized_context(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"vehicles": [', encoding="utf-8")
    with pytest.raises(AuthorizationConfigurationError) as error:
        load_authorizations(path, 2)
    assert error.value.code == "INVALID_JSON"
    assert str(tmp_path) not in str(error.value)


def test_allows_shared_authorized_slot(tmp_path):
    registry = load_authorizations(write_config(tmp_path, config(record("A"), record("B"))), 1)
    assert registry.lookup("A").space_id == registry.lookup("B").space_id == 0


def test_registry_and_records_are_immutable(tmp_path):
    registry = load_authorizations(write_config(tmp_path, config(record())), 1)
    with pytest.raises(TypeError):
        registry.records["OTHER"] = registry.lookup("ABC-123")
    with pytest.raises(AttributeError):
        registry.lookup("ABC-123").authorized = False


def test_missing_or_unreadable_path_is_wrapped(tmp_path):
    missing = tmp_path / "missing.json"
    with pytest.raises(AuthorizationConfigurationError) as error:
        load_authorizations(missing, 2)
    assert error.value.code == "FILE_READ_ERROR"
    assert str(tmp_path) not in str(error.value)
    with pytest.raises(AuthorizationConfigurationError) as error:
        load_authorizations(tmp_path, 2)
    assert error.value.code == "FILE_READ_ERROR"


@pytest.mark.parametrize("capacity", [0, -1, True, 1.5])
def test_capacity_must_be_positive_strict_integer(tmp_path, capacity):
    with pytest.raises(AuthorizationConfigurationError) as error:
        load_authorizations(write_config(tmp_path, config()), capacity)
    assert error.value.code == "INVALID_CAPACITY"
