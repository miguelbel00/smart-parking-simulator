# Vehicle Lifecycle Specification

## Purpose

Define the observable behavior of `Vehicle(Thread)` and the vehicle-facing shutdown semantics of `ParkingLot.close(wait: bool = True)`: each vehicle is an independent execution thread that coordinates its lifecycle through the parking lot, moves through the states CREATED, WAITING, PARKED, FINISHED, and terminates gracefully on close without forced termination. Signatures are preserved from `AGENTS.md`: `Vehicle(Thread)` receives `vehicle_id`, `parking`, `parking_duration`.

Out of scope: admission return values, snapshot contents, and event payload composition (see `parking-capacity` and `parking-events`). The state names here describe observable vehicle behavior; the REQUIRED states are the event-visible minimum defined by the project contract and MUST NOT be removed.

## Requirements

### Requirement: Vehicle threads are independent execution units

The system MUST represent each vehicle as an independent execution thread. Each accepted vehicle MUST run its lifecycle inside its own thread, coordinating state transitions with the `ParkingLot` it was admitted to.

No idle thread may be created solely for animation or UI purposes; this spec covers vehicle threads only.

#### Scenario: Admitted vehicle runs in its own thread

- GIVEN an open `ParkingLot` and a `Vehicle` instance constructed with an identifier, the lot, and a positive `parking_duration`
- WHEN the vehicle is admitted with `admit(vehicle)`
- THEN the vehicle's thread is started and the vehicle progresses through its lifecycle states independent of the calling thread
- AND the vehicle eventually reaches a terminal outcome (finished normally, or cancelled by close) without additional external drive

#### Scenario: Multiple vehicles progress concurrently

- GIVEN several vehicles admitted with overlapping parking durations
- WHEN their threads run concurrently
- THEN their state transitions are observable independently, and no vehicle's progress depends on another vehicle reaching a terminal state first (beyond ordinary capacity waiting)

### Requirement: Lifecycle states

Each accepted vehicle MUST progress through the states CREATED, WAITING, PARKED, FINISHED in that order for a full normal cycle. These states MUST remain representable; no state from this set MAY be removed.

- `CREATED`: the vehicle thread has been created (before or at admission)
- `WAITING`: the vehicle is waiting for an available space
- `PARKED`: the thread has acquired a space and holds it for `parking_duration`
- `FINISHED`: the vehicle thread has terminated its lifecycle (normally, or cancelled by close)

A vehicle admitted while a space is immediately available SHOULD transition from creation directly to the parked state without a distinct observable waiting period.

A vehicle admitted while no space is available MUST transition to the waiting state and MUST NOT become parked until it acquires a space.

#### Scenario: Full cycle with available space

- GIVEN an open `ParkingLot` with at least one free space
- WHEN a vehicle with a short `parking_duration` is admitted and allowed to run
- THEN the vehicle becomes parked promptly after admission, without a preceding waiting interval
- AND after `parking_duration` elapses, the vehicle exits and finishes

#### Scenario: Full cycle through waiting

- GIVEN a full open `ParkingLot`
- WHEN an additional vehicle is admitted
- THEN that vehicle is observable in the waiting state before becoming parked
- AND upon a release it becomes parked, and after its `parking_duration` elapses it exits and finishes

#### Scenario: No out-of-order lifecycle transitions

- GIVEN any vehicle in any scenario, including close during contention
- WHEN its lifecycle is observed via published events or snapshot counters
- THEN the observed order is CREATED, then optionally WAITING, then PARKED (Enter) only while holding a space, and FINISHED last
- AND a vehicle MUST never be observed entering after finishing

### Requirement: Graceful close rejects and cancels appropriately

When `ParkingLot.close()` is invoked, the system MUST reject all subsequent admission requests (returning `False`), MUST cancel every vehicle currently waiting for a space so that it reaches FINISHED without parking, and MUST allow every vehicle currently parked to complete its parking duration, exit, and finish.

The system MUST NOT forcibly terminate any vehicle thread; every vehicle reaches FINISHED by its own transition.

A vehicle cancelled while waiting MUST reach FINISHED without ever reaching the parked state in this shutdown scenario.

#### Scenario: Admission rejected after close

- GIVEN a `ParkingLot` that has been closed
- WHEN `admit(vehicle)` is called with a new vehicle
- THEN `admit` returns `False` promptly
- AND that vehicle's thread is not started and no space is consumed for it

#### Scenario: Waiter cancelled by close reaches FINISHED without parking

- GIVEN a full closed `ParkingLot` and at least one vehicle in the waiting state
- WHEN `close` cancels the waiting vehicle
- THEN that vehicle transitions from WAITING directly to FINISHED
- AND it never reaches PARKED, acquires no space, and does not alter `occupied_count`
- AND it does not emit an entry event (see `parking-events` for the exact published sequence)

#### Scenario: Repeated close is safe

- GIVEN a closed `ParkingLot`
- WHEN `close()` is called again
- THEN the call is accepted without error and no additional cancellation or state change is required

### Requirement: Parked vehicles complete on close

On close, each parked vehicle MUST retain its acquired space until it completes. After its `parking_duration` elapses it MUST exit and finish, and its space MUST be released according to `parking-capacity` exclusive-ownership rules.

After close and completion of all still-running vehicles, the park MUST eventually converge to `occupied_count = 0` for all accepted vehicles that were still active.

#### Scenario: Parked vehicle completes and releases normally after close

- GIVEN a closed `ParkingLot` where a vehicle is currently parked with a known `parking_duration`
- WHEN that duration elapses and the vehicle exits
- THEN the vehicle finishes normally
- AND its space becomes unoccupied (`occupied_count` decreases by 1)

### Requirement: close(wait=True) joins active threads

The system MUST implement `close(wait=True)` such that, when called from a thread other than any vehicle thread, the call returns only after every vehicle admitted before close has reached FINISHED and its thread has terminated.

After `close(wait=True)` returns, the system MUST leave no vehicle thread still running, waiting, or parked among vehicles admitted before close.

#### Scenario: wait=True guarantees no active threads

- GIVEN an open `ParkingLot` with some parked and some waiting vehicles
- WHEN `close(wait=True)` is called from a non-vehicle thread
- THEN the call does not return until all previously admitted vehicle threads are no longer alive
- AND after return, no vehicle thread remains alive or waiting
- AND the returned lot's occupied state converges to empty over the same period of time that it took to finish

#### Scenario: wait=True with no vehicles

- GIVEN a lot with zero previously admitted vehicles
- WHEN `close(wait=True)` is called
- THEN the call returns promptly and results in a lot that rejects any admission

### Requirement: Close with wait=False returns promptly

The system MUST implement `close(wait=False)` such that the call returns promptly — without waiting for parked or waiting vehicles to finish — while still rejecting new admissions and cancelling waiters.

The system MUST NOT guarantee that all events have been published or threads joined at the moment `close(wait=False)` returns; the owning caller is responsible for the lifetime of the shared event queue (see `parking-events`).

#### Scenario: wait=False returns while a parked vehicle is still active

- GIVEN an open lot with one vehicle parked whose `parking_duration` has not elapsed
- WHEN `close(wait=False)` is called
- THEN the call returns promptly, and that vehicle may still be running at return time
- AND it validates that new admissions are rejected immediately after the call returns

#### Scenario: wait=False converges later

- GIVEN `close(wait=False)` was called while a vehicle was parked
- WHEN that vehicle's `parking_duration` elapses
- THEN the vehicle finishes normally and eventually no vehicle threads remain alive
- AND its published events stay consistent with the exclusive-ownership and bounded-capacity invariants (see `parking-capacity`)
