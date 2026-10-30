"""Behavioral proof for Stop temprano/tardio/repetido and Reinicio.

Every test drives the real spawn-based MultiprocessController and its IPC
transport -- this is control-flow/lifecycle behavior (Stop, repeated Stop,
sequential runs on the same engine process), not a FIFO/capacity decision,
so it needs the real engine rather than an in-process shortcut. Tests react
to live events read with blocking controller.get(timeout=...) calls and act
immediately; nothing here sleeps for a guessed duration.
"""

import pytest

from core.events import (
    SIMULATION_FINISHED,
    VEHICLE_CANCELLED,
    VEHICLE_CREATED,
    VEHICLE_ENTERED,
    VEHICLE_EXITED,
    VEHICLE_FINISHED,
    VEHICLE_REJECTED,
)
from simulation.multiprocess import MultiprocessController
from simulation.scenarios import build_payload, get_scenario


def _drain_events(controller, on_event=None, timeout=20):
    """Collect every event message up to and including SIMULATION_FINISHED.

    on_event(message) may react to a specific event (e.g. call
    controller.stop(run_id)) as soon as it is observed -- this is the real
    synchronization mechanism used throughout, never a fixed sleep.
    """
    events = []
    while True:
        message = controller.get(timeout=timeout)
        if message.get("kind") == "failure":
            pytest.fail(f"engine failed: {message}")
        if message.get("kind") != "event":
            continue
        events.append(message)
        if on_event is not None:
            on_event(message)
        if message["name"] == SIMULATION_FINISHED:
            return events


def _plate_events(events, plate):
    return [event for event in events if event["payload"].get("plate") == plate]


def test_stop_early_cancels_pending_and_allows_parked_to_finish():
    payload = build_payload("stop_cancellation_demo")
    controller = MultiprocessController(payload["config"]["capacity"], context="spawn")
    controller.start_engine()
    try:
        run_id = controller.start(payload)
        stopped = False

        def react(message):
            nonlocal stopped
            # React to VEHICLE_CREATED, not VEHICLE_WAITING: the admission
            # worker only flushes a vehicle's WAITING event once its *next*
            # eligibility pass breaks out of its predicate loop (e.g. when
            # the occupant it is waiting behind departs) -- confirmed by
            # tracing real event timestamps, WAITING for STOP-B is
            # generated immediately but not delivered until STOP-A exits.
            # CREATED is flushed unconditionally and immediately by
            # ParkingLot.admit() itself, so it is the reliable real-time
            # signal that a request is now pending.
            if (not stopped and message["name"] == VEHICLE_CREATED
                    and message["payload"]["plate"] == "STOP-B"):
                controller.stop(run_id)
                stopped = True

        events = _drain_events(controller, on_event=react)
    finally:
        controller.shutdown()

    assert stopped, "STOP-B was never created; scenario timing assumption broke"

    stop_b = _plate_events(events, "STOP-B")
    stop_b_names = [event["name"] for event in stop_b]
    assert VEHICLE_ENTERED not in stop_b_names, "a cancelled pending request must never enter"
    assert stop_b_names.count(VEHICLE_CANCELLED) == 1
    cancelled = next(event for event in stop_b if event["name"] == VEHICLE_CANCELLED)
    assert cancelled["payload"]["reason"] == "STOP_REQUESTED"

    stop_a = _plate_events(events, "STOP-A")
    stop_a_names = [event["name"] for event in stop_a]
    assert stop_a_names.index(VEHICLE_ENTERED) < stop_a_names.index(VEHICLE_EXITED) < stop_a_names.index(VEHICLE_FINISHED)

    assert sum(event["name"] == VEHICLE_FINISHED for event in events) == 1
    assert sum(event["name"] == VEHICLE_CANCELLED for event in events) == 1
    assert sum(event["name"] == VEHICLE_REJECTED for event in events) == 0


def test_stop_late_with_nothing_pending_cancels_nothing():
    payload = build_payload("normal_entry_and_exit")
    controller = MultiprocessController(payload["config"]["capacity"], context="spawn")
    controller.start_engine()
    try:
        run_id = controller.start(payload)
        stopped = False

        def react(message):
            nonlocal stopped
            if not stopped and message["name"] == VEHICLE_ENTERED:
                controller.stop(run_id)
                stopped = True

        events = _drain_events(controller, on_event=react)
    finally:
        controller.shutdown()

    assert stopped, "the single vehicle never entered; scenario timing assumption broke"
    assert sum(event["name"] == VEHICLE_CANCELLED for event in events) == 0
    assert sum(event["name"] == VEHICLE_EXITED for event in events) == 1
    assert sum(event["name"] == VEHICLE_FINISHED for event in events) == 1


def test_stop_repeated_does_not_duplicate_terminal_events():
    payload = build_payload("stop_cancellation_demo")
    controller = MultiprocessController(payload["config"]["capacity"], context="spawn")
    controller.start_engine()
    try:
        run_id = controller.start(payload)
        stopped = False

        def react(message):
            nonlocal stopped
            # Same reliable-signal reasoning as the early-stop test: react
            # to CREATED, not WAITING (see comment there).
            if (not stopped and message["name"] == VEHICLE_CREATED
                    and message["payload"]["plate"] == "STOP-B"):
                controller.stop(run_id)
                controller.stop(run_id)
                stopped = True

        events = _drain_events(controller, on_event=react)
    finally:
        controller.shutdown()

    assert stopped, "STOP-B was never created; scenario timing assumption broke"

    for plate in ("STOP-A", "STOP-B"):
        terminal_names = [event["name"] for event in _plate_events(events, plate)
                          if event["name"] in (VEHICLE_FINISHED, VEHICLE_CANCELLED)]
        assert len(terminal_names) == 1, f"{plate} produced duplicated terminal events: {terminal_names}"

    assert sum(event["name"] == VEHICLE_CANCELLED for event in events) == 1
    assert sum(event["name"] == VEHICLE_FINISHED for event in events) == 1


def test_restart_runs_are_independent():
    scenario = get_scenario("capacity_saturation_and_release")
    payload = build_payload("capacity_saturation_and_release")
    controller = MultiprocessController(payload["config"]["capacity"], context="spawn")
    controller.start_engine()
    try:
        run_id_1 = controller.start(payload)
        events_1 = _drain_events(controller)

        run_id_2 = controller.start(payload)
        events_2 = _drain_events(controller)

        controller.shutdown()
    except BaseException:
        controller.shutdown()
        raise

    assert run_id_1 != run_id_2
    assert all(event["run_id"] == run_id_1 for event in events_1)
    assert all(event["run_id"] == run_id_2 for event in events_2)

    # The same plates are reused verbatim: zero rejections in run 2 proves
    # _active_plates did not leak across runs (a leak would collide on every
    # plate, since all five were already "active" at the end of run 1 until
    # each FINISHED and was discarded).
    assert sum(event["name"] == VEHICLE_REJECTED for event in events_2) == 0

    # Vehicle numbering restarts at 1 for the new run rather than continuing
    # from run 1's count.
    created_first = next(event for event in events_2
                         if event["name"] == VEHICLE_CREATED and event["payload"]["plate"] == "SAT-A")
    assert created_first["payload"]["vehicle_id"] == 1

    # Core occupancy/Semaphore state did not carry over: run 2 reaches the
    # same peak concurrent occupancy as a fresh run would, reconstructed
    # strictly from its own event stream.
    occupied = {}
    concurrent = 0
    peak = 0
    for event in events_2:
        if event["name"] == VEHICLE_ENTERED:
            space_id = event["payload"]["space_id"]
            assert space_id not in occupied
            occupied[space_id] = event["payload"]["plate"]
            concurrent += 1
            peak = max(peak, concurrent)
        elif event["name"] == VEHICLE_EXITED:
            space_id = event["payload"]["space_id"]
            occupied.pop(space_id)
            concurrent -= 1
    assert not occupied
    assert concurrent == 0
    assert peak == scenario.capacity
