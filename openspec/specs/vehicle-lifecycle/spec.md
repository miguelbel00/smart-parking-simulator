# Vehicle Request Lifecycle Specification

## Purpose

Define the lifecycle of a vehicle admission request in `ParkingLot`. A `Vehicle` is request data, not an execution thread; the lot's admission and departure workers perform transitions.

## Requirements

### Requirement: Vehicle is a request, not a thread

The system MUST represent each vehicle as a `Vehicle` request object containing its identifier, parking lot, duration, plate, and lifecycle state. `Vehicle` MUST NOT inherit from `Thread` and MUST NOT create a per-vehicle worker. Each parking-lot execution uses its task-oriented admission and departure workers to coordinate requests.

#### Scenario: Admission enqueues request data

- GIVEN a started open `ParkingLot` and a valid `Vehicle` request
- WHEN `admit(vehicle)` accepts it
- THEN the request is active and queued for processing, but need not yet be parked
- AND no thread is created for that vehicle

### Requirement: Request lifecycle transitions

The request lifecycle MUST follow one of these paths:

- Rejected admission: received → rejected; it never becomes active.
- Accepted normal request: accepted/created → waiting (when it cannot enter immediately) → parked → finished.
- Accepted pending request on early stop: accepted/created → optional waiting → cancelled.

`WAITING`, `PARKED`, `FINISHED`, and `CANCELLED` describe the request data's state, not a vehicle thread. `PARKED` means the request physically holds its authorized space. A cancelled request was accepted but never parked. `FINISHED` means only normal completion after an occupied stay and release; it MUST NOT mean cancellation.

#### Scenario: Request is rejected without activation

- GIVEN a request that fails validation, authorization, uniqueness, or open-lot checks
- WHEN `admit` rejects it
- THEN the request is not active and does not enter waiting or parked state
- AND its rejection reason is returned and reported as `VEHICLE_REJECTED`

#### Scenario: Accepted request parks and finishes

- GIVEN an accepted request and an available authorized space
- WHEN admission assigns that space and the requested stay completes
- THEN the request proceeds to PARKED, releases the physical space after its stay, and reaches FINISHED
- AND its occupied space is not made available before release

#### Scenario: Accepted request waits then parks

- GIVEN an accepted request whose authorized space is not available
- WHEN it waits and that space becomes eligible
- THEN it remains WAITING until it acquires the authorized space
- AND after its stay it releases the space and reaches FINISHED

#### Scenario: Early stop cancels a pending request

- GIVEN an accepted request still pending when early close requests cancellation
- WHEN core cancels pending requests
- THEN the request transitions from WAITING (or accepted/created if waiting was not yet observable) directly to CANCELLED
- AND it never becomes PARKED, acquires a space, or reaches FINISHED
- AND its active-plate membership is released

### Requirement: Bounded capacity and exclusive slot ownership

The parking lot MUST use a semaphore to enforce configured capacity and synchronization via its lock/condition to protect shared request and slot state. A semaphore permit is acquired only when physical occupancy is committed and released exactly once on exit. Waiting requests MUST NOT hold permits.

Only one request may occupy a physical slot at a time. The project owner's approved policy MUST serve requests in acceptance order among eligible requests, with strict FIFO per authorized slot. If the oldest request's slot is occupied, an eligible request for another free authorized slot MAY proceed. This avoids unnecessary global blocking; it is not strict global FIFO. Arrival means acceptance under the core lock, not concurrent call start time. The active-plate membership MUST prevent duplicate active requests and be released on either normal completion or cancellation. JSON authorization MUST bind a plate to its specific slot; reassignment is forbidden.

#### Scenario: Capacity remains bounded

- GIVEN concurrent accepted requests competing for a finite-capacity lot
- WHEN they are admitted, parked, released, or cancelled
- THEN occupied requests never exceed capacity and no two requests occupy the same slot simultaneously
- AND each occupied request holds exactly one permit until release

#### Scenario: Slot and plate become available after termination

- GIVEN a request occupying a slot or an accepted request cancelled while pending
- WHEN it completes normally or is cancelled
- THEN its physical slot (if occupied) and active-plate membership are released exactly once
- AND a later eligible request may proceed

### Requirement: Graceful lot close

Close mode is selected on first close and may only escalate toward cancellation
afterward. Stop during natural draining MUST cancel requests still pending;
neither repeated calls nor an already-computed natural close may undo Stop.
Occupancy/cancellation linearizes under the existing condition lock: a request
already parked finishes normally, otherwise it is cancelled exactly once.

`close(wait: bool = True, cancel_pending: bool = True)` MUST mark the lot closed and reject subsequent admissions. `cancel_pending=True` requests cancellation of accepted pending requests while allowing parked requests to complete; `cancel_pending=False` allows accepted pending requests to drain normally. `wait=True` joins started workers and returns only after the selected cancellation/drain behavior completes. `wait=False` does not join workers or guarantee that work has drained on return. Workers MUST NOT be forcibly terminated.

The Simulator selects `cancel_pending` from whether an early stop was requested: early stop cancels pending requests, while natural completion drains them. Parked requests complete normally on either path.

#### Scenario: Admission after close is rejected

- GIVEN a closed lot
- WHEN a new request is submitted
- THEN it is rejected promptly and consumes no slot or semaphore permit

#### Scenario: Parked request completes after close

- GIVEN a request parked when the lot is closed
- WHEN its stay completes
- THEN it releases its slot and permit and reaches FINISHED

#### Scenario: Waiting close does not return before drain

- GIVEN accepted pending and parked requests when `close(wait=True)` is called externally
- WHEN close returns
- THEN pending requests have been drained or cancelled according to the close mode, parked requests have completed, and no lot worker remains active

#### Scenario: Stop escalates natural draining

- GIVEN a natural close is draining accepted pending and parked requests
- WHEN explicit Stop requests cancellation
- THEN pending requests become CANCELLED exactly once while parked requests finish normally
- AND a later natural-close call cannot reverse the cancellation

### Requirement: Process ownership and IPC lifecycle

The spawn engine MUST own the lifecycle state and task-oriented workers.
Validated multiprocessing queues MUST carry commands, events and selected
audit records to/from the parent. The parent transport MUST audit received
events once and project them to the local Tk queue. A local queue alone is not
IPC. This architecture is implemented; complete academic compliance still
requires evidence against the applicable requirements.

#### Scenario: Lifecycle terminals reach the parent before completion

- GIVEN accepted requests in a spawned run
- WHEN the run drains or cancels pending requests
- THEN terminals cross IPC before normal simulation finish
- AND confirmed audit drain precedes declaring the audited run successful
