"""Evidence of effective concurrency between generation, admission, and
departure in a real spawn+IPC run of the fifo_per_slot scenario.

Every assertion here reads only the real `origin` metadata (process_id,
process_name, thread_name) that simulation/multiprocess.py already attaches
to each IPC event message, and the real event timestamps. Nothing is
simulated or fabricated: this proves the architecture uses a small, fixed
set of task-oriented worker threads (not one thread per vehicle) running in
a genuine separate OS process, with admission/departure work interleaved
with generation rather than serialized after it.
"""

import os

from core.events import (
    SIMULATION_FINISHED,
    VEHICLE_CREATED,
    VEHICLE_ENTERED,
    VEHICLE_EXITED,
    VEHICLE_FINISHED,
    VEHICLE_WAITING,
)
from simulation.multiprocess import MultiprocessController
from simulation.scenarios import build_payload

SCENARIO_NAME = "fifo_per_slot"

PRODUCER_THREAD = "simulation-producer"
ADMISSION_THREAD = "parking-admission"
DEPARTURE_THREAD = "parking-departures"


def test_concurrency_evidence_from_real_spawn_and_ipc():
    payload = build_payload(SCENARIO_NAME)
    controller = MultiprocessController(payload["config"]["capacity"], context="spawn")
    controller.start_engine()
    try:
        controller.start(payload)
        events = []
        while True:
            message = controller.get(timeout=20)
            if message.get("kind") == "failure":
                raise AssertionError(f"engine failed: {message}")
            if message.get("kind") != "event":
                continue
            events.append(message)
            if message["name"] == SIMULATION_FINISHED:
                break
    finally:
        controller.shutdown()

    # 1. Real multiprocessing boundary: one single child process handled the
    # whole run, and it differs from this test process.
    process_ids = {message["origin"]["process_id"] for message in events}
    assert len(process_ids) == 1
    assert process_ids != {os.getpid()}

    # 2. Task-oriented threads, not one thread per vehicle: exactly the three
    # fixed worker threads appear across all 4 vehicles' events.
    thread_names = {message["origin"]["thread_name"] for message in events}
    assert thread_names == {PRODUCER_THREAD, ADMISSION_THREAD, DEPARTURE_THREAD}

    # 3-5. Each kind of work happens on its own dedicated thread.
    for message in events:
        name = message["name"]
        thread_name = message["origin"]["thread_name"]
        if name == VEHICLE_CREATED:
            assert thread_name == PRODUCER_THREAD
        elif name in (VEHICLE_WAITING, VEHICLE_ENTERED):
            assert thread_name == ADMISSION_THREAD
        elif name in (VEHICLE_EXITED, VEHICLE_FINISHED):
            assert thread_name == DEPARTURE_THREAD

    # 6. Effective concurrency, not serialization: admission already acted
    # (FIFO-A entered) before the producer finished generating all arrivals
    # (FIFO-D's VEHICLE_CREATED comes last, ~3s after FIFO-A's arrival at
    # t~1s with 1s fixed spacing). This proves the admission worker was not
    # waiting for the producer to finish before doing its own work.
    created_timestamps = [m["payload"]["timestamp"] for m in events if m["name"] == VEHICLE_CREATED]
    entered_timestamps = [m["payload"]["timestamp"] for m in events if m["name"] == VEHICLE_ENTERED]
    assert len(created_timestamps) == 4
    assert entered_timestamps, "expected at least one VEHICLE_ENTERED event"
    last_created = max(created_timestamps)
    assert min(entered_timestamps) < last_created, (
        "admission should start before the producer finishes generating all arrivals"
    )

    assert sum(m["name"] == VEHICLE_FINISHED for m in events) == 4
