# Parking Events Specification

## Purpose

Define the immutable shared event payload `ParkingEvent` and the ordered lifecycle publication rules for core: which event types core emits, when, into the supplied `queue.Queue`, and how optional fields (`vehicle_id`, `space_id`, `waiting_time`) are populated. This spec pins down the two user-approved behavior decisions: a vehicle cancelled while waiting by `close` emits the existing `VEHICLE_FINISHED` event (no new event type such as `VEHICLE_CANCELLED` is introduced), and `waiting_time` is present only on `VEHICLE_ENTERED`, measured from waiting start to space acquisition.

Signatures preserved from `AGENTS.md` (section 4): the immutable shared dataclass `ParkingEvent` with fields `type: str`, `timestamp: float`, `vehicle_id: int | None = None`, `space_id: int | None = None`, `waiting_time: float | None = None`; event types `VEHICLE_CREATED`, `VEHICLE_WAITING`, `VEHICLE_ENTERED`, `VEHICLE_EXITED`, `VEHICLE_FINISHED`, `SIMULATION_STARTED`, `SIMULATION_FINISHED`.

Out of scope: UI consumption, snapshots and admission mechanics (`parking-capacity`, `vehicle-lifecycle`), and ownership of `SIMULATION_STARTED`/`SIMULATION_FINISHED` by `Simulator`.

## Requirements

### Requirement: Immutable event payload

The system MUST define `ParkingEvent` as an immutable dataclass supporting no attribute mutation after construction, with exactly the documented fields and defaults listed above.

The system MUST publish all core vehicle lifecycle events into the `queue.Queue` supplied at lot construction, never through any UI or Tkinter surface.

#### Scenario: Event instances reject mutation

- GIVEN a `ParkingEvent` instance constructed with any valid field values
- WHEN any code attempts to assign to one of its attributes after construction
- THEN the attempt fails and the instance keeps its constructed values

#### Scenario: Events reach the shared queue

- GIVEN an accepted vehicle progressing through its lifecycle against a supplied `queue.Queue`
- WHEN lifecycle state transitions occur
- THEN each corresponding event is observable by draining that queue
- AND no core-emitted event appears through any channel other than the supplied queue

### Requirement: Core event vocabulary

The system MUST emit only the seven established event type names. Core MUST emit only vehicle lifecycle events: `VEHICLE_CREATED`, `VEHICLE_WAITING`, `VEHICLE_ENTERED`, `VEHICLE_EXITED`, and `VEHICLE_FINISHED`.

Core MUST NOT emit `SIMULATION_STARTED` or `SIMULATION_FINISHED`; those types remain reserved for `Simulator`.

Core MUST NOT introduce additional event types for shutdown outcomes, including but not limited to any `VEHICLE_CANCELLED` type.

#### Scenario: Core queue drains with only vehicle lifecycle event types

- GIVEN a run covering admission, contention, and shutdown (including cancelled waiters and completed parked vehicles)
- WHEN the queue is drained after all admitted vehicles finish
- THEN every event `type` belongs to `VEHICLE_CREATED`, `VEHICLE_WAITING`, `VEHICLE_ENTERED`, `VEHICLE_EXITED`, `VEHICLE_FINISHED`
- AND no event type outside this set — including `SIMULATION_STARTED`, `SIMULATION_FINISHED`, or a cancellation-specific type — is present from core

#### Scenario: Cancelled waiting vehicle emits the existing FINISHED event

- GIVEN a full lot where a vehicle is waiting and a close call occurs
- WHEN the close cancels that waiting vehicle
- THEN that vehicle emits the existing `VEHICLE_FINISHED` event type
- AND no additional or new event type is emitted for this cancellation

### Requirement: Event field population rules

The system MUST populate event fields as follows:

1. Every core vehicle lifecycle event MUST carry the emitting vehicle in `vehicle_id` (never `None` for core vehicle events).
2. `VEHICLE_CREATED` MUST NOT carry `space_id` or `waiting_time`.
3. `VEHICLE_WAITING` MUST NOT carry `space_id` or `waiting_time`.
4. `VEHICLE_ENTERED` MUST carry `space_id` (the acquired space) and `waiting_time` (never `None`), where `waiting_time` is nonnegative and measures from the vehicle's waiting start until it acquired the space.
5. `VEHICLE_EXITED` MUST carry `space_id` — the same space the vehicle's `VEHICLE_ENTERED` reported for that vehicle — and MUST NOT carry `waiting_time`.
6. `VEHICLE_FINISHED` MUST NOT carry `space_id` or `waiting_time`, whether the vehicle finished normally or was cancelled by close while waiting.

#### Scenario: VEHICLE_ENTERED carries acquired space and waiting time

- GIVEN a vehicle admitted while the lot is full, which later acquires a space
- WHEN the corresponding `VEHICLE_ENTERED` event is observed
- THEN `waiting_time` is present and greater than or equal to zero, matching the interval from the vehicle's waiting start to space acquisition
- AND `vehicle_id` and `space_id` are non-null

#### Scenario: Immediate entry has a nonnegative waiting time

- GIVEN a vehicle admitted while a space was immediately available
- WHEN its `VEHICLE_ENTERED` event is observed
- THEN `waiting_time` is present and greater than or equal to zero (approximately zero for immediate acquisition)
- AND it is measured from the vehicle's waiting-start point, not from simulated arrival of other vehicles

#### Scenario: Waiting and finished events carry no space or waiting time

- GIVEN any vehicle's lifecycle events are drained from the queue
- WHEN each event is inspected
- THEN `VEHICLE_WAITING`, `VEHICLE_FINISHED`, and `VEHICLE_CREATED` have `space_id = None` and `waiting_time = None`
- AND `vehicle_id` is non-null on each of them

#### Scenario: Entry and exit of one vehicle share the same space id

- GIVEN a vehicle that entered with `space_id = k` and later exited
- WHEN its `VEHICLE_EXITED` event is observed
- THEN `space_id` equals `k` for that same vehicle event pair
- AND `waiting_time` on the exit event is `None`

### Requirement: Ordered single-pass lifecycle publication

The system MUST publish, for each accepted vehicle, lifecycle events that reflect its internal state transition order exactly, with no duplicates and no out-of-order entries:

- Normal cycle: `VEHICLE_CREATED` → (`VEHICLE_WAITING`, only when waiting occurs) → `VEHICLE_ENTERED` → `VEHICLE_EXITED` → `VEHICLE_FINISHED`, each exactly once for a normal single-cycle vehicle.
- Cancelled-by-close cycle: `VEHICLE_CREATED` → (`VEHICLE_WAITING`, only if observed before close) → `VEHICLE_FINISHED` — with no `VEHICLE_ENTERED` and no `VEHICLE_EXITED` events for the cancelled vehicle.

The system MUST NOT publish out-of-order combinations such as `VEHICLE_ENTERED` after `VEHICLE_FINISHED` for the same vehicle, or duplicate events for the same lifecycle transition.

#### Scenario: Normal full lifecycle order

- GIVEN a vehicle admitted with a space available and a positive `parking_duration`
- WHEN it runs to completion
- THEN events for that vehicle appear in the queue in the order CREATED, ENTERED, EXITED, FINISHED with no `VEHICLE_WAITING` event
- AND each appears exactly once

#### Scenario: Waiting cycle order

- GIVEN a vehicle admitted while the lot is full, which later acquires a space after a release
- WHEN it runs to completion
- THEN events for that vehicle appear in the order CREATED, WAITING, ENTERED, EXITED, FINISHED, with each present exactly once
- AND no event for that vehicle appears out of this order even under concurrent admission of other vehicles
#### Scenario: Cancelled waiting vehicle order

- GIVEN a full lot with a waiting vehicle, followed by `close`
- WHEN that waiting vehicle is cancelled by the close
- THEN that vehicle's events appear in the order CREATED, WAITING, FINISHED
- AND no `VEHICLE_ENTERED` or `VEHICLE_EXITED` is emitted for that vehicle after close
