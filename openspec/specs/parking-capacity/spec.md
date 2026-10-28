# Parking Capacity Specification

## Purpose

Specify the current `ParkingLot` capacity, admission, authorization, and snapshot
contract, while recording the mandatory academic multiprocessing/IPC
requirement separately from implementation status. Multiprocessing and IPC are
not implemented; their ownership and design remain pending agreement.

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
the current task-worker implementation, not a claim that multiprocessing/IPC
is complete.

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

The academic requirement MUST respect arrival order and serve the longest-
waiting vehicle first when that vehicle is authorized for its specific slot and
that slot is available. The policy for an oldest request whose authorized slot
is blocked is unresolved and MUST NOT be inferred from implementation behavior.

The current runtime scans for eligible requests and preserves strict FIFO among
requests for the same authorized slot, allowing an eligible request for another
slot to proceed. This describes current behavior, not a settled interpretation
of the unresolved academic policy.

#### Scenario: Longest-waiting eligible request

- GIVEN multiple waiting requests whose authorized slots are available
- WHEN the lot selects a request to occupy a released slot
- THEN the eligible request with the longest wait is served first

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

The first close selects draining or cancellation. A later explicit Stop MUST
be able to escalate an active natural drain to cancellation of pending requests.
Once cancellation is selected, a later stale natural close MUST NOT downgrade
it. The lot remains closed to new admissions throughout.

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

#### Scenario: Stop escalates an active natural drain

- GIVEN accepted pending and parked requests after `close(wait=False, cancel_pending=False)` begins
- WHEN a later `close(wait=False, cancel_pending=True)` requests Stop
- THEN pending requests are cancelled and parked requests finish normally
- AND a subsequent `cancel_pending=False` close does not restore draining

### Requirement: Multiprocessing and IPC academic requirement

The delivered academic system MUST use real multiprocessing and inter-process
communication. This is a mandatory requirement but is NOT implemented by the
current runtime. Process responsibility split, concrete IPC mechanism, and
ownership/synchronization of critical shared state MUST be agreed before
implementation or changes to shared public contracts. Do not treat the current
in-process `queue.Queue` event contract as IPC or replace it unilaterally.

#### Scenario: IPC design is coordinated before implementation

- GIVEN multiprocessing/IPC work is proposed
- WHEN responsibilities and interfaces are planned
- THEN the team agrees on process ownership, IPC, critical-state synchronization,
  and compatibility with current module/event contracts before implementation
