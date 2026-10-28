import pytest

from simulation.authorizations import load_authorizations
from simulation.ipc_protocol import validate_start_payload
from simulation.scenarios import build_payload, get_scenario, list_scenarios


def test_fifo_per_slot_payload_matches_the_real_ipc_contract():
    payload = build_payload("fifo_per_slot")
    assert validate_start_payload(payload) == payload


def test_build_payload_rejects_overrides_outside_editable_fields():
    with pytest.raises(ValueError):
        build_payload("fifo_per_slot", overrides={"capacity": 5})


def test_build_payload_allows_declared_editable_overrides():
    payload = build_payload("fifo_per_slot", overrides={"min_arrival_time": 0, "max_arrival_time": 0})
    assert payload["config"]["min_arrival_time"] == 0
    assert payload["config"]["max_arrival_time"] == 0
    validate_start_payload(payload)


def test_fifo_per_slot_fixture_is_schema_valid_for_its_declared_capacity():
    scenario = get_scenario("fifo_per_slot")
    registry = load_authorizations(scenario.authorization_path, scenario.capacity)
    assert len(registry.records) == len(scenario.plate_sequence)


def test_get_unknown_scenario_raises():
    with pytest.raises(KeyError):
        get_scenario("does-not-exist")


def test_list_scenarios_exposes_fifo_per_slot_with_its_editable_fields():
    summaries = {summary.name: summary for summary in list_scenarios()}
    assert "fifo_per_slot" in summaries
    summary = summaries["fifo_per_slot"]
    assert summary.editable_fields == (
        "max_arrival_time", "max_parking_time", "min_arrival_time", "min_parking_time",
    )
