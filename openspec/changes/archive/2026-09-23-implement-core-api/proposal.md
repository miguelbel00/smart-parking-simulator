# Proposal: Implement the Core Parking API

## Intent

Implement the team-approved, currently unimplemented core contract so the simulator and UI can safely admit vehicle threads, observe parking state, and consume lifecycle events. This gives the project a testable concurrency foundation without changing the shared API or taking over integration owned by other modules.

## Scope

### In Scope

- Implement immutable `ParkingEvent` and the existing event types in `core/events.py`; core publishes only vehicle lifecycle events to the supplied `queue.Queue`.
- Implement `Vehicle(Thread)` and `ParkingLot` in `core/vehicle.py` and `core/parking.py`, preserving the documented constructors and `admit(vehicle) -> bool`, `snapshot() -> ParkingSnapshot`, and `close(wait: bool = True) -> None` signatures. Include copied, immutable snapshots, safe admission, space assignment/release, waiting, and graceful shutdown.
- Add focused concurrency and event tests in `tests/`, including capacity, unique spaces, eventual admission, cancellation on close, nonblocking admission while full, snapshot consistency, and event ordering/fields; run `python -m pytest`.

### Out of Scope

- UI, simulation, or `main.py` implementation and integration; in particular, UI responsiveness must be verified in a later integration phase.
- Changes to shared event names, event fields, public signatures, or the root/module API contract.
- Additional lifecycle event types (including `VEHICLE_CANCELLED`) or simulation start/finish emission from core.

## Capabilities

### New Capabilities

- `parking-capacity`: Asynchronous vehicle admission, semaphore-limited capacity, exclusive space allocation, and immutable consistent parking snapshots.
- `vehicle-lifecycle`: Vehicle thread states and graceful shutdown: cancel waiters, allow parked vehicles to finish, reject new admissions, and optionally wait for active threads.
- `parking-events`: Immutable shared event payload and ordered core lifecycle publication, including approved cancellation and waiting-time semantics.

### Modified Capabilities

None; `openspec/specs/` has no existing capability specs to revise.

## Approach

Keep all capacity waits inside each `Vehicle` thread. Use `threading.Semaphore` to gate spaces and a `threading.Lock` around admission/shutdown state, a reusable fixed-space allocation map, counters, and snapshot copies. Follow the exploration's recommended cancellation strategy: closing marks the lot closed and wakes waiters using semaphore tokens; every awakened vehicle rechecks closure before assignment so a wake token cannot create phantom occupancy. Design must account for each acquire/release and races among admission, parking, and close. Parked vehicles finish naturally; `close(wait=True)` joins active threads without forced termination.

Publish core events through the queue, never through Tkinter. A waiter cancelled by close emits the existing `VEHICLE_FINISHED` event, not a new type. `waiting_time` is set only on `VEHICLE_ENTERED`, from wait start until a space is acquired, and is `None` for every other event. Derive the precise event/state ordering and shutdown accounting in specs and design before implementation.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `core/events.py` | Modified | Define immutable event model and established event type names. |
| `core/parking.py` | Modified | Implement lot, synchronization, safe snapshot, and close policy. |
| `core/vehicle.py` | Modified | Implement threaded lifecycle and queue-based event publication. |
| `tests/` | New | Add deterministic core behavior and concurrency regression tests. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Close wake tokens race with normal releases and allow phantom occupancy or double release. | Medium | Specify token ownership and post-acquire close checks; test close during contention and repeated shutdown. |
| Event order or snapshot counters disagree during concurrent transitions. | Medium | Synchronize state transitions and publication; assert per-vehicle ordering and snapshot invariants under load. |
| `close(wait=False)` permits late events, while calling `close(wait=True)` from a vehicle thread could self-join. | Medium | Document caller-owned queue lifetime and external-thread-only joining in design; test both close modes. |
| Timing-based concurrency tests become flaky. | Medium | Use coordinated start/wait signals, short durations, bounded joins, and invariant assertions rather than unbounded sleeps. |

## Rollback Plan

Revert only this change's implementation and tests in `core/events.py`, `core/parking.py`, `core/vehicle.py`, and `tests/` to the contract-first skeleton. Preserve `AGENTS.md`, the shared event names and signatures, and other modules; rerun `python -m pytest` to verify the prior baseline. Do not ship a partial core API to downstream modules.

## Dependencies

- Existing team-approved contract in `AGENTS.md` and `core/AGENTS.md`; Python standard-library threading/queue and available pytest for tests. No new runtime dependency.
- Before implementation, follow the repository's `feature/core` branch policy; branch creation from `main` was raised but not explicitly confirmed in exploration, so do not assume authorization to change branches in this phase.

## Success Criteria

- [ ] Documented public signatures, immutable payloads/snapshots, and the seven established event names remain unchanged; core has no Tkinter/UI/simulation dependency.
- [ ] `admit` starts accepted vehicle threads without waiting for capacity; `snapshot().occupied_count` never exceeds capacity, and live vehicles never share a space.
- [ ] A released space can be reused by a waiting vehicle; `close()` rejects new admissions, cancels waiters with `VEHICLE_FINISHED`, and allows parked vehicles to finish; `close(wait=True)` leaves no active admitted threads.
- [ ] Each admitted vehicle emits lifecycle events in valid order; only `VEHICLE_ENTERED` has `waiting_time`, measured from wait start to space acquisition.
- [ ] Core tests pass using `python -m pytest`, including concurrent contention and shutdown cases; UI freeze testing remains deferred.
