# Parking Capacity Specification

## Purpose

Specify the current `ParkingLot` capacity, admission, authorization, and snapshot
contract within the implemented spawn-engine/validated-IPC architecture.
Implementation evidence and tests do not alone certify every academic requirement.

## Requirements

### Requirement: Public admission and capacity contract

The current runtime MUST expose `ParkingLot(capacity, event_queue,
authorization_registry)` with `start()`, `admit(vehicle) -> AdmissionResult`,
`snapshot() -> ParkingSnapshot`, and
`close(wait: bool = True, cancel_pending: bool = True) -> None`. Admission MUST
validate and enqueue synchronously without waiting for capacity. An accepted
result means the request is active/queued, not parked. Rejections MUST report
one stable reason: `UNKNOWN_PLATE`, `NOT_AUTHORIZED`, `DUPLICATE_ACTIVE`,
`LOT_CLOSED`, or `INVALID_REQUEST`.

The lot MUST enforce its configured capacity with a semaphore, acquiring a
permit only when physical occupancy is committed and releasing it exactly once
on departure. A lock/condition MUST protect shared transitions and coordinate
workers without active polling. No per-vehicle threads are permitted; this is
the task-worker implementation inside the engine process, not a thread or
process per vehicle.

#### Scenario: Full lot does not block admission

- GIVEN a started lot at capacity
- WHEN a valid authorized vehicle request is submitted
- THEN `admit` returns promptly with an accepted result
- AND the request does not consume a permit until occupancy is committed
- AND occupied count never exceeds capacity

#### Scenario: Invalid or closed request is rejected

- GIVEN a request that is invalid, unauthorized, duplicate-active, or submitted
  after close
- WHEN `admit` processes the request
- THEN it returns the corresponding stable rejection reason
- AND the request is not active and consumes no slot or permit

### Requirement: Fixed-slot authorization and active-plate uniqueness

The JSON authorization registry MUST be validated completely before workers
start and supplied to core as an immutable registry. A plate MUST only occupy
its assigned specific slot; core MUST NOT reassign it to another slot. An
active plate MUST be rejected as `DUPLICATE_ACTIVE` until its accepted request
finishes or is cancelled. Slot ownership and active-plate registration MUST be
released consistently and exactly once on the applicable terminal transition.

#### Scenario: Authorized slot is unavailable

- GIVEN a valid plate assigned to a specific occupied slot
- WHEN its request is admitted
- THEN the request waits without occupying a different slot
- AND the slot may be assigned again only after its current owner releases it

#### Scenario: Plate registration is released

- GIVEN an accepted request that finishes normally or is cancelled while
  pending
- WHEN its terminal transition is completed
- THEN its active-plate registration is released exactly once
- AND any physically occupied slot and semaphore permit are released exactly
  once

### Requirement: Arrival order and eligible FIFO

The project owner has definitively adopted FIFO among eligible requests, with
strict FIFO per authorized slot. Requests MUST be considered in acceptance order
under the core lock; concurrent call start times do not define arrival order.
A request is eligible when its assigned slot is free and no older pending
request targets that same slot. Only validated authorized requests enter the
pending queue. No request MAY occupy a different slot.

An occupied slot MUST NOT block eligible requests for other slots. Once the
blocked slot is released, its oldest still-eligible pending request MUST be
served before younger requests for that slot. This avoids unnecessary global
blocking while preserving FIFO among requests competing for the same resource.
It is not strict global FIFO and is not pending professor approval. There is
no bounded-wait guarantee if a slot never becomes available; early close cancels
pending requests, while natural close drains them after occupants finish.

`Condition(Lock())` protects acceptance, selection, occupancy and release. The
semaphore is acquired only at occupancy commit and released on departure;
pending requests do not hold permits.

#### Scenario: Longest-waiting eligible request

- GIVEN multiple waiting requests whose authorized slots are available
- WHEN the lot selects a request to occupy a released slot
- THEN the eligible request with the longest wait is served first

#### Scenario: A blocked slot does not stop another eligible request

- GIVEN an occupant holds slot 0 and A is waiting for slot 0
- WHEN B is accepted after A for free authorized slot 1
- THEN B enters slot 1 while A keeps waiting for slot 0
- AND neither request may occupy an unauthorized slot
- AND when slot 0 is released A enters before a younger request for slot 0

#### Validation evidence and review status

`tests/test_parking.py` covers this contract through:

- `test_same_slot_fifo_and_progress_on_other_slot`: controlled releases verify
  blocked A, progress of B, eventual entry of A and same-slot ordering.
- `test_oldest_eligible_request_is_selected_before_later_eligible_request`:
  event-coordinated selection among requests for distinct free slots.
- `test_three_same_slot_requests_enter_in_fifo_order_across_releases` and
  `test_concurrent_slot_releases_preserve_capacity_and_progress_fifo`:
  repeated per-slot FIFO, exclusive authorized occupancy and permit recovery.
- `test_admission_commit_racing_with_close_has_one_terminal_outcome`, early-close
  and natural-drain tests: accepted requests terminate without duplicate outcomes.
- `test_rejection_reasons_and_duplicate_active_for_waiting_and_parked` and
  `test_concurrent_same_plate_admission_has_single_winner`: active-plate exclusion.

The controlled-release tests adjust private deadlines under the condition lock
to avoid depending on short dwell times; assertions use admission results,
snapshots, vehicle states and lifecycle events, with a white-box permit check.
Successful tests are bounded evidence, not proof that all races or deadlocks
are impossible.

Engram's latest available review record (2026-10-24, observation 490) reports
`review-5d649f61e49db666` awaiting `review-reliability` because native capture
transport was unavailable. It records no admitted verdict. This historical
administrative pending state is not evidence of a FIFO defect, nor a current
live-status confirmation. Changes to tests do not inherit review of older bytes.

Validation on 2026-10-24 in the local working tree:

- The two previously uncommitted tests passed before adjustment (2 passed in
  60.08 s). Their intent is retained; controlled releases now avoid long waits
  and per-slot assertions no longer require an unsupported global entry order.
  The close test observes the closed predicate before releasing publication and
  checks thread errors and agreement between terminal event and vehicle state.
- `.venv/bin/python -m pytest tests/test_parking.py tests/test_vehicle_lifecycle.py tests/test_app_shutdown.py -q -p no:cacheprovider -W error::pytest.PytestUnhandledThreadExceptionWarning`:
  41 passed in 1.32 s.
- `.venv/bin/python -m pytest -q -p no:cacheprovider -W error::pytest.PytestUnhandledThreadExceptionWarning`:
  223 passed in 12.96 s.
- Independent technical verification in an external scratch copy found no
  change-caused blockers; parking tests passed (27), and two additional probe
  cases passed against both candidate and baseline production. This is not a
  native review verdict. Those exploratory probes are not repository tests.

FIFO is functionally closed within this contract: production is unchanged and
no in-scope functional defect is known from these checks. The two improved tests
were uncommitted at that validation date, as requested. Native assessment of this change reported
`medium`, `review_due: false`, `under_budget`; no replacement review was started
and no approval of the historical transaction is claimed. Successful tests do
not certify all academic requirements or absence of every race/deadlock.

### Requirement: Exclusive spaces and immutable snapshots

At most one vehicle MAY physically occupy a slot at any time, and occupied
count MUST never exceed capacity. `snapshot()` MUST return an immutable/copied
view with `capacity`, `occupied_count`, `waiting_count`, and
`occupied_spaces: tuple[tuple[int, int], ...]`. It MUST satisfy
`occupied_count == len(occupied_spaces)` and MUST NOT expose mutable internal
state or mutate the lot.

#### Scenario: Concurrent activity preserves snapshot invariants

- GIVEN concurrent admissions, departures, and snapshot reads
- WHEN snapshots are observed throughout the run
- THEN occupied count never exceeds capacity
- AND each slot appears at most once in occupied spaces
- AND a previously returned snapshot is unchanged by later state transitions

### Requirement: Graceful shutdown

Every close MUST reject later requests. `cancel_pending=True` (the default)
requests cancellation of accepted requests still waiting; parked requests are
allowed to finish. `cancel_pending=False` allows accepted pending requests to
drain normally. `wait=True` (the default) joins both started lot workers and
returns only after the selected drain/cancellation behavior completes;
`wait=False` returns without joining or guaranteeing that work has drained.
Workers MUST NOT be forcibly terminated. The Simulator uses
`cancel_pending=stop_requested.is_set()`: an early stop requests pending
cancellation, while natural completion drains accepted requests.

#### Scenario: Close waits for completion

- GIVEN accepted waiting and parked requests
- WHEN `close(wait=True, cancel_pending=False)` returns
- THEN all accepted requests have drained to their normal terminal outcomes
- AND no lot worker remains active

#### Scenario: Early close cancels pending requests and waits

- GIVEN accepted waiting and parked requests
- WHEN `close(wait=True, cancel_pending=True)` returns
- THEN pending requests are cancelled and parked requests finish normally
- AND no lot worker remains active

### Requirement: Multiprocessing and IPC academic requirement

The runtime MUST preserve the spawn engine's ownership of ParkingLot and
Simulator, validated multiprocessing command/output queues, and the parent
transport's projection to the local Tk event queue. The local Tk queue is not
IPC. Changes to ownership or public contracts require coordination.

#### Scenario: Engine and parent preserve state ownership

- GIVEN a simulation run in the child engine
- WHEN commands, events and selected audit records cross IPC
- THEN only engine workers mutate parking state under core synchronization
- AND the parent validates messages, audits them through its single file writer,
  and delivers events to Tk without worker widget access
