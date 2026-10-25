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

The engine uses validated multiprocessing IPC for commands, events and
selected audit records. The parent transport delivers immutable events to the
in-process Tk `queue.Queue`; that local queue is not IPC. `run_id` and origin
metadata travel in the envelope without changing `ParkingEvent`.

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

The parent MUST own one `AuditSession` with a `QueueHandler`, local logging
queue, `QueueListener` and UTF-8 file per application session. Child producers
MUST forward selected operation/error records through the existing validated
IPC; they MUST NOT open independent audit files. Received canonical events are
audited once per run/sequence key before projection to the local Tk queue.
`ParkingEvent` and IPC v1 schemas remain unchanged.

Each Simulator `admission_attempt` MUST correlate by `run_id` and `vehicle_id`
with CREATED or REJECTED. CREATED is evidence that the relevant admission
checks passed (valid request, known authorized plate, no duplicate active plate,
started/open lot); it does not prove occupancy. A rejected result records the
first applicable stable reason, not a transcript of every internal check.
Malformed requests may lack valid identifiers. No redundant decision rows or
per-check events are required.

The existing tab-separated key/value format appends `waiting_time`, `result`
and `error_summary`; existing column names and order are retained. Absent values
are `-`. Historical logs are not rewritten. Consumers requiring fixed column
counts must accept appended fields; consumers of child error text must use
`error_summary` rather than the former misleading `traceback` value.

| Canonical event | Persisted result | Interpretation |
|---|---|---|
| VEHICLE_CREATED | ACCEPTED | Accepted/enqueued, not parked |
| VEHICLE_WAITING | WAITING | Observable waiting for the authorized resource |
| VEHICLE_ENTERED | PARKED | Occupancy/assignment committed |
| VEHICLE_EXITED | RELEASED | Physical slot released |
| VEHICLE_FINISHED | FINISHED | Normal completion after occupancy |
| VEHICLE_REJECTED | REJECTED | Rejected with the original stable reason |
| VEHICLE_CANCELLED | CANCELLED | Pending request cancelled; STOP_REQUESTED |

`reason` MUST retain the canonical event value, including absence; no successful
validation or waiting explanation is invented. The result and event semantics
provide the explanation when no reason is carried. Simulation boundary events
and non-event rows retain `result=-`.

`waiting_time` MUST preserve the original elapsed seconds calculated using
Core's monotonic enqueue/occupancy times. It is populated on ENTERED only, not
recomputed from wall-clock timestamps or WAITING. WAITING is optional: Core
marks waiting when selection finds no eligible request; it need not occur at
acceptance, and its absence does not imply zero elapsed wait. Cancelled pending
requests have no computed occupancy wait duration; do not invent one.

`timestamp` is parent registration time; `event_time` is the original event or
child audit message time when available. `origin_process_id`,
`origin_process_name` and `origin_thread_name` describe the producer, while
`processName` and `threadName` describe parent reception/registration, not the
physical writer thread. Legacy IPC messages may omit origin metadata, which
remains unknown rather than being attributed to the parent. Existing run and
vehicle correlation is sufficient for these outcomes; no new sequence or
command-ID fields are needed. No global cross-thread chronology is promised.

Child error payload `error` remains IPC-v1-compatible exception-only text,
bounded by the child to 1000 characters before escaping. It MUST be persisted
as `error_summary` alongside `exception_type`, operation, run and available
origin; it MUST NOT be presented as a complete traceback. `traceback=-` for
these messages; parent-local exceptions retain their actual traceback. Do not
add source lines, locals or request payloads to child summaries. Exception
messages can still contain sensitive data; callers must avoid secrets and log
access must be protected. This is not a universal redaction guarantee.

`audit_confirmed`/`audit_complete` MUST retain technical confirmation/drain
semantics, not academic certification or crash-proof durability. Observed queue,
transport, sequence, writer or barrier failures MUST prevent silent confirmed
success. Stop, restart and shutdown MUST preserve the existing drain ordering.

#### Scenario: Core waiting duration survives the process boundary

- GIVEN an authorized vehicle admitted by the spawn engine
- WHEN ENTERED crosses IPC and AuditSession drains to the parent file
- THEN persisted waiting_time equals the received original duration in seconds
- AND vehicle/run/plate, authorized/physical slots and producer origin correlate
- AND acceptance and occupancy remain distinct single canonical records

#### Scenario: Cancellation, isolation and errors remain reconstructable

- GIVEN normal, rejected and early-stopped requests across successive runs
- WHEN records are read after confirmed drain and shutdown
- THEN each accepted request has one FINISHED or CANCELLED terminal, not both
- AND a cancelled pending request has no occupancy record
- AND rejection reasons and run boundaries are preserved
- AND a child error is represented as a bounded summary, not a stack trace

Regression evidence lives in `tests/test_audit_logging.py`,
`tests/test_multiprocess.py` and the protocol, adapter, main and shutdown tests.
GUI state, aggregate metrics and stdout do not replace persisted audit records.
SQLite is excluded. Tests are bounded evidence, not proof against every race,
deadlock or abrupt process/filesystem failure.

### Requirement: Bounded Tk event-consumer recovery

The consumer MUST calculate the next canonical projection before widget effects.
A removed event MUST NOT be requeued or have its dispatch replayed after a
partial render failure. One reconstruction per run MAY restore slots, plates,
waiting requests and counters from canonical state without recording metrics
again. Recovered finish handling MUST still wait for actual drain before
enabling restart. There MUST be at most one scheduled normal polling callback.

The parent adapter's `report_ui_error` MUST use the existing AuditSession and
current run context, not a new IPC event or writer. If unavailable, Tk/stderr
provides a bounded diagnostic fallback. If reconstruction fails or another
dispatch fails in that run, the UI MUST request Stop and controlled close,
draining canonical events without retrying the broken widget path. Failed
visual state MUST NOT be represented as successful recovery. A broken status
widget MUST NOT prevent shutdown checks and resource draining.
