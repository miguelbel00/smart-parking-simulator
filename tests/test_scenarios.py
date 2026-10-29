import re

import pytest

from simulation.authorizations import load_authorizations
from simulation.config import PARKING_CAPACITY
from simulation.ipc_protocol import validate_start_payload
from simulation.scenarios import build_payload, get_scenario, list_academic_scenarios, list_scenarios


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


def test_all_scenarios_use_the_configured_parking_capacity():
    for scenario in (get_scenario(name) for name in (
        "fifo_per_slot",
        "capacity_saturation_and_release",
        "authorization_rejections",
        "normal_entry_and_exit",
        "stop_cancellation_demo",
    )):
        assert scenario.capacity == PARKING_CAPACITY == 6
        assert build_payload(scenario.name)["config"]["capacity"] == 6


def test_multiprocessing_lifecycle_payload_has_realistic_concurrent_activity():
    payload = build_payload("normal_entry_and_exit")

    assert len(payload["plate_sequence"]) == 30
    assert payload["config"]["total_vehicles"] == 30
    assert payload["config"]["min_arrival_time"] == 1
    assert payload["config"]["max_arrival_time"] == 1
    assert payload["config"]["min_parking_time"] == 12
    assert payload["config"]["max_parking_time"] == 12
    assert len(payload["authorization"]["vehicles"]) == 30
    assert validate_start_payload(payload) == payload
    requirement = get_scenario("normal_entry_and_exit").academic_requirement
    assert "multiprocessing" in requirement
    assert "IPC real" in requirement


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


def test_academic_selector_exposes_exactly_the_three_requested_scenarios():
    scenarios = list_academic_scenarios()

    assert [scenario.name for scenario in scenarios] == [
        "authorization_rejections",
        "capacity_saturation_and_release",
        "normal_entry_and_exit",
    ]
    assert [scenario.title for scenario in scenarios] == [
        "Escenario 1 — Control de acceso y autorizaciones",
        "Escenario 2 — Concurrencia, capacidad y FIFO",
        "Escenario 3 — Multiprocessing, IPC y ciclo de vida",
    ]


def test_academic_payloads_use_six_spaces_and_the_requested_sequences():
    authorization = build_payload("authorization_rejections")
    capacity = build_payload("capacity_saturation_and_release")
    lifecycle = build_payload("normal_entry_and_exit")

    assert authorization["config"]["capacity"] == 6
    assert authorization["plate_sequence"] == [
        "OND-830", "BZO-132", "NGX-553", "OND-830", "CWR-850",
    ]
    assert capacity["config"]["capacity"] == 6
    assert capacity["plate_sequence"] == [
        "QDQ-021", "YQO-792", "UHD-319", "INZ-019", "FFQ-932", "PVD-377",
        "BIV-976", "ZON-782", "JJK-247",
    ]
    assert lifecycle["config"]["capacity"] == 6
    assert len(lifecycle["plate_sequence"]) > 6


def test_academic_scenario_plates_use_static_aaa_000_values():
    plate_pattern = re.compile(r"[A-Z]{3}-[0-9]{3}")
    expected_unknown = {"authorization_rejections": {"BZO-132"}}

    for scenario in list_academic_scenarios():
        payload = build_payload(scenario.name)
        sequence = payload["plate_sequence"]
        authorized = {record["plate"] for record in payload["authorization"]["vehicles"]}

        assert all(plate_pattern.fullmatch(plate) for plate in sequence)
        assert set(sequence) - authorized == expected_unknown.get(scenario.name, set())
