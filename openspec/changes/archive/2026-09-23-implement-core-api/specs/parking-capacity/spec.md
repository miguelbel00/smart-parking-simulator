# Parking Capacity Specification

## Purpose

Define the observable admission and capacity behavior of `ParkingLot`: asynchronous nonblocking admission of vehicle threads, capacity bounded by a counting gate, exclusive ownership of parking spaces, and immutable consistent snapshots of lot state. This spec preserves the public contract from `AGENTS.md`: `ParkingLot(capacity: int, event_queue: Queue)` exposing `admit(vehicle: Vehicle) -> bool`, `snapshot() -> ParkingSnapshot`, and `close(wait: bool = True) -> None`.

Out of scope: UI rendering, simulation orchestration, `main.py` composition, and the event payload/ordering details covered by `parking-events`.

## Requirements

### Requirement: Nonblocking admission

The system MUST accept or reject a vehicle via `admit(vehicle) -> bool` without the calling thread ever blocking or sleeping in wait for a parking space. Admission acceptance MUST mean the vehicle's independent execution thread is registered and started, NOT that the vehicle immediately received a space.

The system MUST return `True` from `admit` exactly when the vehicle was accepted and started, and MUST NOT use `admit`'s return value to signal space availability.

#### Scenario: Admission accepted when a space is available

- GIVEN a `ParkingLot` with capacity greater than zero and fewer occupied spaces than capacity
- WHEN the caller calls `admit(vehicle)`
- THEN `admit` returns `True` promptly (without waiting on capacity)
- AND the vehicle's thread is started
- AND the vehicle subsequently reaches the parked state

#### Scenario: Admission accepted while the lot is full

- GIVEN a `ParkingLot` whose all spaces are currently occupied
- WHEN the caller calls `admit(vehicle)`
- THEN `admit` returns `True` promptly, without the calling thread being blocked in `admit`
- AND the vehicle transitions to the waiting state and does NOT count toward occupied spaces

#### Scenario: Admission must not create occupied state synchronously beyond capacity

- GIVEN a `ParkingLot` at full occupied capacity
- WHEN `admit` returns `True` for an accepted vehicle
- THEN an immediate `snapshot()` MUST show `occupied_count` less than or equal to `capacity`
        - AND `waiting_count` reflects accepted vehicles that have entered the `WAITING` state and have not yet acquired a space

#### Scenario: Admission rejected after close

- GIVEN a `ParkingLot` that has been closed
- WHEN the caller calls `admit(vehicle)`
- THEN `admit` returns `False` promptly
- AND the vehicle's thread is not started
- AND no space is reserved for that vehicle

### Requirement: Bounded capacity

The system MUST ensure that the number of concurrently parked vehicles never exceeds the configured `capacity` at any observable moment, including under concurrent admission and release cycles.

The system MUST NOT allow a vehicle to enter the parked state while all spaces are occupied; the vehicle MUST wait until a space is released by another vehicle.

#### Scenario: Never more parked vehicles than capacity

- GIVEN a `ParkingLot` with `capacity = 2`
- WHEN more than two vehicles are admitted concurrently
- THEN every observation taken at any time shows `snapshot().occupied_count <= 2`
- AND at most two `space_id` values appear simultaneously across live vehicles

#### Scenario: Occupancy returns to zero after all cycles complete

- GIVEN a `ParkingLot` with capacity `N` and `M > N` admitted vehicles whose parking durations and wait times all elapse
- WHEN all admitted vehicles eventually finish
- THEN `snapshot().occupied_count` becomes `0`

### Requirement: Exclusive space ownership

The system MUST guarantee that at any moment each `space_id` is owned by at most one live vehicle. No two concurrently parked vehicles MAY share the same `space_id`.

When a vehicle releases a space, the system MAY assign that same `space_id` to a different vehicle afterwards; the exclusivity rule applies to concurrent ownership only.

#### Scenario: Two vehicles never owned the same space simultaneously

- GIVEN several vehicles admitted to a `ParkingLot` with fewer spaces than admitted vehicles
- WHEN vehicle observations (snapshots and per-vehicle enter/exit records) are collected during a run or stress cycle
- THEN no `space_id` value is ever associated with two live vehicles at the same time
- AND a recorded conflict of any `space_id` constitutes a contract violation

#### Scenario: A released space can be reused by another vehicle

- GIVEN a vehicle `A` parked in `space_id = 3`, which then exits
- WHEN another vehicle `B` later acquires a space
- THEN `B` MAY receive `space_id = 3`
- AND the assignment MUST occur only after `A` released the space (no overlapping ownership)

### Requirement: Waiters enter when space is released

The system MUST eventually admit a waiting vehicle to the parked state once at least one space becomes free, when the lot is still open. A released space MUST NOT remain unused indefinitely while vehicles wait.

The system MUST keep waiting vehicles out of occupied counts while they wait; their pending state MUST be observable as a waiting count in the snapshot.

#### Scenario: Wait then entry upon release

- GIVEN a full `ParkingLot` with `capacity = 1` and two admitted vehicles `A` and `B`
- WHEN `A` acquires the single space and later exits, releasing it
- THEN `B` eventually transitions from waiting to parked and emits entry in the same state transition window
- AND `B` never occupied a second simultaneous space
- AND `snapshot().occupied_count` goes back to `1` after the release, held by `B`

#### Scenario: Waiting vehicles are visibly waiting before a space frees

- GIVEN a full `ParkingLot` and at least one extra admitted vehicle
- WHEN a snapshot is taken before any occupied vehicle exits
- THEN `snapshot().waiting_count` is greater than zero
- AND `snapshot().occupied_count` equals `capacity`

### Requirement: Immutable consistent snapshots

The system MUST expose `snapshot() -> ParkingSnapshot` such that returning a snapshot MUST NOT expose internal mutable structures by reference: subsequent state changes to the lot MUST NOT alter a previously returned snapshot value.

Each snapshot MUST contain at least the fields `capacity: int`, `occupied_count: int`, `waiting_count: int`, and `occupied_spaces: tuple[tuple[int, int], ...]` — one `(space_id, vehicle_id)` pair per currently parked vehicle.

The system MUST ensure internal consistency of each snapshot: `occupied_count` MUST equal the length of `occupied_spaces`, and `waiting_count` MUST match the number of live accepted vehicles currently waiting for a space at the snapshot's creation time.

The system MUST NOT allow snapshot reads to mutate parking state; reading a snapshot MUST NOT change admission, allocation, or wait outcomes.

#### Scenario: Snapshot invariants under load

- GIVEN several vehicles admitted concurrently while others enter and exit
- WHEN snapshots are taken repeatedly during the run
- THEN every snapshot satisfies `occupied_count == len(snapshot.occupied_spaces)` AND `occupied_count <= capacity`
- AND every `space_id` appears at most once in each snapshot's `occupied_spaces`

#### Scenario: Snapshot is not mutated by later events

- GIVEN a snapshot `s1` was taken at time `t` showing some occupied state
- WHEN later vehicles enter, exit, or are cancelled
- THEN `s1` still shows exactly the values observed at time `t`
- AND no later mutation of lot state MUST affect the contents of `s1` or the outcomes of other vehicles

#### Scenario: Empty-lot snapshot

- GIVEN a `ParkingLot` with `capacity = 2` and no admitted vehicles
- WHEN `snapshot()` is taken
- THEN `occupied_count = 0`, `waiting_count = 0`, and `occupied_spaces` is an empty tuple
- AND `capacity` is reported as `2`
