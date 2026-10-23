# Parking Events Specification

## Purpose

Define the immutable `ParkingEvent` payload and the lifecycle events published by `ParkingLot` and `Simulator` to the shared queue. Core vehicle events describe request state; simulation boundary events belong to `Simulator`.

## Requirements

### Requirement: Immutable shared event payload

The system MUST define frozen dataclass `ParkingEvent` with fields in this order, preserving the original five positional fields and appending the three optional fields:

| Field | Type | Default |
|---|---|---|
| `type` | `str` | required |
| `timestamp` | `float` | required |
| `vehicle_id` | `int \| None` | `None` |
| `space_id` | `int \| None` | `None` |
| `waiting_time` | `float \| None` | `None` |
| `plate` | `str \| None` | `None` |
| `authorized_space_id` | `int \| None` | `None` |
| `reason` | `str \| None` | `None` |

Core MUST publish vehicle events through its supplied event queue. The UI consumes that shared queue; workers MUST NOT update Tkinter directly.

The current event transport is an in-process `queue.Queue`, not IPC. The
academic requirement for real multiprocessing and IPC is mandatory but not
implemented; do not alter this queue contract or event payload without
agreement on process ownership and transport.

The authorization JSON MUST be validated as a complete registry before
workers start, and each plate MUST remain bound to its configured specific
slot. Duplicate active plates MUST be rejected; their registration is released
consistently when the request finishes or is cancelled. These admission
outcomes use the existing event contract and do not authorize reassignment.

#### Scenario: Payload cannot be mutated

- GIVEN a constructed `ParkingEvent`
- WHEN code attempts to assign to any field
- THEN the assignment fails and the original value is unchanged

### Requirement: Event vocabulary and ownership

The shared vocabulary MUST be `VEHICLE_CREATED`, `VEHICLE_WAITING`, `VEHICLE_ENTERED`, `VEHICLE_EXITED`, `VEHICLE_FINISHED`, `VEHICLE_REJECTED`, `VEHICLE_CANCELLED`, `SIMULATION_STARTED`, and `SIMULATION_FINISHED`.

Core MUST publish vehicle lifecycle events. `Simulator` MUST publish `SIMULATION_STARTED` and `SIMULATION_FINISHED` to the execution's forwarding queue. A rejection is an admission outcome, not an active request, and MUST emit `VEHICLE_REJECTED` without `VEHICLE_CREATED`. `VEHICLE_CREATED` MUST be emitted only after acceptance.

#### Scenario: Rejected request has no active lifecycle

- GIVEN an invalid, unauthorized, duplicate-active, or closed-lot admission request
- WHEN core rejects it
- THEN the result is represented by `VEHICLE_REJECTED` and no `VEHICLE_CREATED`, `VEHICLE_WAITING`, entry, exit, finish, or cancellation event is emitted for that request
- AND it is not added to active requests or active-plate membership

### Requirement: Event field meanings and population

Core vehicle events MUST carry `vehicle_id` when the request supplies a valid identifier; malformed requests may have `vehicle_id = None`. `plate` is the normalized plate (trimmed and uppercased) when available. `authorized_space_id` identifies the registry-assigned slot and is independent of physical occupancy. `space_id` MUST be populated only for physical entry or release, never merely to report authorization.

- `VEHICLE_CREATED`: accepted request; carries its normalized `plate` and `authorized_space_id`; has no physical `space_id` or `waiting_time`.
- `VEHICLE_WAITING`: accepted request waiting for its authorized slot; carries plate/authorized slot and no physical `space_id` or `waiting_time`.
- `VEHICLE_ENTERED`: physical occupancy begins; carries occupied `space_id`, authorized slot, and nonnegative `waiting_time` measured from enqueue time to acquisition.
- `VEHICLE_EXITED`: physical occupancy is released; carries the same `space_id` as entry and the authorized slot; has no `waiting_time`.
- `VEHICLE_FINISHED`: normal completion after the occupied stay and exit; carries plate/authorized slot and no `space_id` or `waiting_time`.
- `VEHICLE_CANCELLED`: accepted pending request cancelled by early stop; carries plate/authorized slot and `reason = STOP_REQUESTED`, with no physical `space_id` or `waiting_time`.
- `VEHICLE_REJECTED`: rejected admission; carries the sanitized request identifier/normalized plate when available, and the authorization slot only when a valid authorized record resolves it. It carries no physical `space_id` or `waiting_time`, and `reason` is one of `UNKNOWN_PLATE`, `NOT_AUTHORIZED`, `DUPLICATE_ACTIVE`, `LOT_CLOSED`, or `INVALID_REQUEST`.

#### Scenario: Authorized slot is distinct from occupied space

- GIVEN an accepted request authorized for slot `k` that is still waiting
- WHEN its CREATED or WAITING event is observed
- THEN `authorized_space_id` is `k` and `space_id` is `None`
- WHEN its ENTERED and EXITED events are observed
- THEN `space_id` identifies the physical occupied/released slot

#### Scenario: Entry records wait duration

- GIVEN an accepted request that reaches physical occupancy
- WHEN `VEHICLE_ENTERED` is published
- THEN `waiting_time` is nonnegative and measures elapsed time from enqueue to acquisition
- AND EXITED and terminal events have no `waiting_time`

### Requirement: Per-request event order and terminal distinction

For each accepted request, core MUST publish exactly one causal lifecycle sequence:

- Normal completion: `VEHICLE_CREATED` → optional `VEHICLE_WAITING` → `VEHICLE_ENTERED` → `VEHICLE_EXITED` → `VEHICLE_FINISHED`.
- Early-stop cancellation while pending: `VEHICLE_CREATED` → optional `VEHICLE_WAITING` → `VEHICLE_CANCELLED`.

`VEHICLE_CANCELLED` MUST represent an accepted request that never parked, and MUST NOT be represented as `VEHICLE_FINISHED`. `VEHICLE_FINISHED` MUST represent only normal completion after a parked stay. Core MUST preserve causal order per request without duplicate transition events.

#### Scenario: Normal request completes

- GIVEN an accepted request that obtains an authorized slot and completes its stay
- WHEN its events are observed
- THEN they appear in CREATED, optional WAITING, ENTERED, EXITED, FINISHED order, each once

#### Scenario: Early stop cancels a pending request

- GIVEN an accepted request still waiting when `close` requests cancellation
- WHEN core terminalizes that request
- THEN its final event is `VEHICLE_CANCELLED` with `reason = STOP_REQUESTED`
- AND it has no ENTERED, EXITED, or FINISHED event

### Requirement: Core events precede simulation completion

When Simulator completes a run, it MUST wait for core to drain and publish all terminal events before publishing `SIMULATION_FINISHED`. Thus every core terminal event for that execution is queued before the simulation-finished event.

#### Scenario: Simulation stop drains accepted requests

- GIVEN a run containing parked and pending accepted requests
- WHEN Simulator completes its stop and emits `SIMULATION_FINISHED`
- THEN all core terminal events for those requests precede `SIMULATION_FINISHED` in the shared queue

### Requirement: Concurrent audit is safe and traceable

The academic system MUST provide concurrent logging that is safe and traceable
across its processes. The current application audit uses a `QueueHandler`, a
`QueueListener`, and a unique UTF-8 file per application session, separate from
the Tk event queue; that describes the present in-process runtime and does not
establish multiprocessing-safe logging. Cross-process logging ownership and
synchronization remain pending design decisions. Event auditing MUST remain
single-pass at the publication adapter and MUST NOT require changing
`ParkingEvent` fields solely to add a run identifier.

Trace records MUST make requests, validation, admission decisions, waits,
entries, exits, and errors reconstructable with timestamps and enough
process/thread/run context to correlate concurrent activity. Logging MUST
avoid exposing sensitive data and MUST NOT let independent unsynchronized
writers mutate critical parking state. The current logger's coverage of every
required trace detail has not been established by this specification update.
