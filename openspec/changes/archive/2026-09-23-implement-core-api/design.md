# Design: Implement the Core Parking API

## Technical Approach

Implement the approved core contract in `core/events.py`, `core/parking.py`, and `core/vehicle.py` only. `ParkingLot` owns capacity, the shared lock, space allocation, thread registration, closure, and queue publication; each `Vehicle(Thread)` performs its own semaphore wait and parking-duration sleep. A single lock linearizes lifecycle transitions and event publication against `snapshot()` and `close()`. See `proposal.md` and the `parking-capacity`, `vehicle-lifecycle`, and `parking-events` delta specs for observable requirements. `main.py`, `simulation/`, and `ui/` are scaffold-only integration context and remain untouched. The UI will consume the shared queue on the main thread; no core thread imports or calls Tkinter.

## Architecture Decisions

### Decision: Separate capacity permits from exclusive space assignment

**Choice**: Use `threading.Semaphore(capacity)` for capacity and a fixed collection of space IDs (for example `0` through `capacity - 1`) with a lock-protected `dict[space_id, vehicle_id]` for ownership. A vehicle must acquire a permit before choosing a free ID under the lock. Release ownership and the corresponding permit once, in the exit transition.

**Alternatives considered**: Use a counter instead of a semaphore; derive availability only from the semaphore; use an ever-increasing space ID.

**Rationale**: The semaphore is mandatory for the academic concurrency model, while a stable, lock-protected allocation map makes duplicate assignments impossible and produces deterministic per-space snapshot pairs. No UI allocation logic is introduced.

### Decision: Wake waiters with semaphore credits and reconcile them at terminal shutdown

**Choice**: At the first close, while holding the lot lock, set `_closed`, count the registered `WAITING` vehicles, and release exactly that many wake credits to the semaphore. Each registered waiter makes exactly one blocking `acquire()` and, on return, checks `_closed` under the lock before claiming a space. A cancelled waiter returns its acquired permit to the semaphore, transitions to `FINISHED`, and never parks. Track `_wake_credits` issued by close; when the final accepted lifecycle finishes, all normal holders have returned their permits and all cancelled waiters have returned acquired permits. Drain exactly `_wake_credits` permits using nonblocking semaphore acquires, once, under the lot lock. This restores the terminal semaphore count to the original capacity. A waiter that was registered but had acquired a real permit just before close still cancels: its unused wake credit is drained at the end. There is no reopen path.

**Alternatives considered**: Timed-acquire polling (introduces a shutdown latency/tunable and repeated wakeups); a `Condition` replacing the semaphore (breaks the mandatory capacity gate); returning an acquired permit without reconciling close credits (silently inflates terminal permit count).

**Rationale**: Posting wake credits avoids polling while preserving the semaphore wait. The lock-serialized post-acquire closure check prevents phantom occupancy; terminal credit reconciliation handles the otherwise unobservable race between acquiring a real permit and committing the parking transition. Never attempt to guess whether an individual `acquire()` consumed a real or a synthetic permit.

### Decision: One lot lock owns transitions, snapshots, and event ordering

**Choice**: Keep `_closed`, `_waiting`, `_active`, `_occupied`, each vehicle's state, and queue insertion of core events in the same lock domain. `admit()` starts and registers a vehicle under the lock, then publishes `VEHICLE_CREATED` before releasing the lock, so the new worker cannot publish a later event first. `Vehicle.run()` calls internal lot transition methods, but performs blocking `Semaphore.acquire()` and `time.sleep(parking_duration)` outside the lock. On immediate `acquire(blocking=False)` success, transition directly to `PARKED`; otherwise register `WAITING`, publish its event, release the lock, and block on the semaphore. The thread never sleeps or waits on capacity in `admit()`.

**Alternatives considered**: Publish after unlocking; let the caller assign a space; hold the lock during blocking acquire; let vehicle threads manipulate the map or UI directly.

**Rationale**: Publication inside short lock-protected transitions gives each vehicle a single-pass observable sequence and prevents `close()` from slipping between acceptance, state changes, and queue ordering. The lot remains the only owner of shared state, and no lock is held during a capacity or duration wait. The supplied queue is the ordinary unbounded `queue.Queue()` specified by project composition; event insertion is nonblocking for that queue.

### Decision: Close joins the fixed admitted-thread set, never from a vehicle

**Choice**: Maintain a retained list of successfully started threads for joins and a separate set of active lifecycles for terminal credit reconciliation. Hold the lot lock across start/registration to prevent an admitted-but-unstarted thread from escaping a concurrent close; roll back registration and publish no CREATED event if thread start fails. At close, prevent new admissions and post wake credits under the lock, copy the retained thread list, release the lock, and optionally join every thread in that copy. Repeated close does not post credits again, but a later `close(wait=True)` still joins. A lot-owned vehicle invoking `close(wait=True)` raises `RuntimeError` before changing close state (self-join would deadlock). `close(wait=False)` returns after posting credits; queue lifetime remains the caller's responsibility.

**Alternatives considered**: Join while holding the lock; join only currently active threads; silently skip a self-join; forcibly terminate parked threads.

**Rationale**: Lock-free joining lets workers finish their locked transitions. Retaining all started threads covers the small interval after FINISHED publication/active-set removal but before the actual thread returns. Fail-fast self-join is safer than silently weakening `wait=True`.

### Decision: Keep payload and state vocabulary unchanged

**Choice**: `ParkingEvent` and `ParkingSnapshot` are frozen dataclasses. Keep the seven approved event strings; core emits only the five `VEHICLE_*` types. Represent `CREATED`, `WAITING`, `PARKED`, and `FINISHED` in `Vehicle` without changing its constructor; expose a lock-safe state read if needed for tests. Use `time.monotonic()` for elapsed waiting time (begin immediately before the first nonblocking acquire, end when a permit is obtained) and `time.time()` for event timestamps. Include `waiting_time` only on `VEHICLE_ENTERED`, including approximately zero on immediate admission; cancellation emits only `VEHICLE_FINISHED` after CREATED/optional WAITING.

**Alternatives considered**: A new cancellation event, waiting time on WAITING/FINISHED, or time-of-day subtraction for duration.

**Rationale**: These preserve the team-approved public contract and avoid skew from wall-clock adjustments. `Vehicle` is an independent thread, while the lot coordinates all event-relevant transitions.

## Data Flow

```text
Caller --admit(vehicle)--> ParkingLot (lock: register/start, CREATED)
                                  |
                                  v
                    Vehicle.run() --try-acquire--> Semaphore
                          |            | failure: WAITING + blocking acquire
                          |            v
                          +------> ParkingLot (lock: closed? cancel : assign/PARKED)
                                             |                  |
                                             |                  v
                                             |             sleep(duration)
                                             |                  |
                                             +<-- exit/release --+
                                             |
                                             v
                              Queue[ParkingEvent] --> future UI consumer
Snapshot reader ---------> ParkingLot (same lock: immutable copied view)
Close caller ------------> ParkingLot (same lock: close + wake; join outside)
```

**Normal sequence**: `admit()` publishes CREATED before the worker's first transition. The worker tries an immediate permit while holding the lot lock. On failure it records WAITING and its event before calling blocking `acquire()` outside the lock. On success it reenters the lock, checks closure, removes itself from the waiting set if applicable, assigns a free space, changes to PARKED, then publishes ENTERED. After sleeping outside the lock, it removes ownership, publishes EXITED with the old space ID, releases one permit, transitions to FINISHED, publishes FINISHED, and removes itself from the active set. The final active transition drains close credits if closure occurred. Each queued event is enqueued while its transition holds the same lock used by `snapshot()`.

**Close race**: Once `_closed` is set under the lock, no new ENTERED transition is permitted. A vehicle already PARKED keeps its space and normal exit path; a registered WAITING vehicle is guaranteed a wake opportunity. If that vehicle has already returned from `acquire()` but has not committed its entry, it still sees closure and returns its permit. A newly started CREATED vehicle not yet registered as WAITING observes closure on its first lock acquisition and finishes without acquiring. Queue consumers may observe later EXITED/FINISHED events after `close(wait=False)` returns.

**Permit ledger**: Before close, every claimed parking space holds one permit. During close, issue `W` extra wake credits once, where `W` is the locked size of the registered waiting set. Every registered waiter ultimately acquires exactly once and, if closed, releases exactly once; normal parked exits release exactly once. After the last admitted lifecycle releases its held permit, the semaphore has `capacity + W` free permits, regardless of whether any waiter took a real or synthetic one. Draining `W` at that point leaves `capacity`; never drain early or issue another batch on a repeated close. No reopen or post-close allocation is allowed.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `core/events.py` | Modify | Define frozen `ParkingEvent` with the exact five fields/defaults and the seven established string constants. |
| `core/parking.py` | Modify | Define frozen `ParkingSnapshot`, capacity/ownership gate, lock-owned transitions and publication, close wake-credit ledger, and public API. |
| `core/vehicle.py` | Modify | Define `Vehicle(Thread)`, its states, and the worker lifecycle delegating synchronized transitions to its lot. |
| `tests/test_events.py` | Create | Verify event immutability, exact fields, vocabulary, and per-event optional fields. |
| `tests/test_parking.py` | Create | Verify admission, snapshots, capacity, uniqueness, reuse, and contention. |
| `tests/test_vehicle_lifecycle.py` | Create | Verify normal/waiting/cancelled ordering, shutdown races, joins, and nonblocking close. |

`tests/.gitkeep` may remain. No other project source, docs, or module contracts need modification for this phase.

## Interfaces / Contracts

```python
@dataclass(frozen=True)
class ParkingEvent:
    type: str
    timestamp: float
    vehicle_id: int | None = None
    space_id: int | None = None
    waiting_time: float | None = None

@dataclass(frozen=True)
class ParkingSnapshot:
    capacity: int
    occupied_count: int
    waiting_count: int
    occupied_spaces: tuple[tuple[int, int], ...]

class Vehicle(Thread):
    def __init__(self, vehicle_id: int, parking: ParkingLot,
                 parking_duration: float) -> None: ...

class ParkingLot:
    def __init__(self, capacity: int, event_queue: Queue) -> None: ...
    def admit(self, vehicle: Vehicle) -> bool: ...
    def snapshot(self) -> ParkingSnapshot: ...
    def close(self, wait: bool = True) -> None: ...
```

- Preserve the exact public parameter names and event fields. `admit` accepts and starts each not-previously-admitted vehicle belonging to the lot only while open; `False` means closed. Neither `admit` nor `snapshot` waits for a space. Constructor rejects nonpositive capacity; invalid vehicle ownership, re-admitting the same thread, or thread-start failure should fail explicitly rather than producing a successful admission without a started thread.
- Private helpers in `core/parking.py` own the semaphore and lock: worker-entry attempt (`closed`, immediate acquire or WAITING registration), post-wait acquire/commit-or-cancel, normal release, cancelled completion, event enqueue, and terminal wake-credit drain. `Vehicle.run()` calls these helpers and does not directly mutate the lot or the event queue. Avoid a runtime import cycle using postponed annotations / `TYPE_CHECKING` for `Vehicle` in `parking.py`.
- `snapshot()` returns a fresh copied, sorted tuple of `(space_id, vehicle_id)` pairs while holding the lock. `occupied_count = len(occupied_spaces)`; `waiting_count = len(_waiting)` counts live workers that entered the WAITING transition and have not yet claimed a space or cancelled. In the scheduling interval just after `admit` returns but before the newly started worker first transitions, that worker is CREATED, not WAITING; a snapshot must not invent a WAITING event or state.
- Normal events: CREATED → optional WAITING → ENTERED → EXITED → FINISHED. Cancelled events: CREATED → optional WAITING → FINISHED. Every core event has a `vehicle_id`, only ENTERED has `waiting_time`, only ENTERED/EXITED have `space_id`; only Simulator will publish `SIMULATION_*`.

## Testing Strategy

The repository has no existing tests or repository-wide TDD gate; write focused pytest tests alongside implementation and run `python -m pytest` (project-local command, `strict_tdd: false`). Use unbounded `Queue`, `threading.Event` barriers or observable queue events, short positive durations, and bounded `join(timeout=...)`/wait deadlines; no unbounded sleeps or reliance on exact interleaving between vehicles. Always close and join started vehicles in `finally` so a failed assertion does not strand test threads.

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | Frozen dataclasses, exact event fields/constants, empty/immutable snapshot, invalid capacity, rejection after close. | `pytest`, `dataclasses.FrozenInstanceError`, constructor/signature and copied-snapshot assertions. |
| Concurrency/integration within core | Full lot returns promptly from `admit`; waiters do not count as parked; release leads to reentry; max occupancy and unique/reusable space IDs across concurrent starts. | Synchronize on ENTERED/WAITING events or polling bounded snapshot invariants; assert per-snapshot ownership and queue per-vehicle histories. |
| Shutdown/race regression | Close while blocked, close after a waiter acquires but before commitment, close with CREATED worker not yet waiting, parked completion, repeated close, `wait=False` followed by `wait=True`, self-join rejection. | Deterministic synchronization barriers at transition boundaries (test-only monkeypatch/wrappers, no production sleeps), bounded joins, assert no late ENTERED, no duplicated FINISHED, no surviving accepted thread, and terminal semaphore accounting after reconciliation; repeat contentious runs to detect races. |
| E2E/UI | No UI process is implemented in this change. | Defer UI responsiveness and queue-draining integration to the UI/simulation integration phase. |

The RED case for the acquired-but-not-committed race must force closure while the waiter holds a permit but has not yet obtained the lot lock; then assert FINISHED without ENTERED and verify that issued wake credits were drained only after all accepted lifecycles ended. For normal-vs-cancelled paths, validate per-vehicle event order and `waiting_time >= 0` on ENTERED only; assert EXITED uses its ENTERED space.

## Threat Matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or external process-integration boundary is changed. Vehicle threads and their synchronization are covered by the concurrency/shutdown tests above rather than the external process threat matrix.

## Migration / Rollout

No data migration or feature flag required. Implement on the project-prescribed `feature/core` branch during apply (do not change branches in this design phase), keep source changes confined to core and tests, and run `python -m pytest` before handing the API to the other module owners. Rollback reverts only the new core implementation and tests to the existing scaffold; retain root/core `AGENTS.md` and shared names/signatures. No partial core API should be integrated downstream.

## Open Questions

- [ ] Confirm before apply whether the repository's `feature/core` branch already exists or should be created through the team's branch workflow; no branch change is part of design.

The user decided that `waiting_count` counts only vehicles that have entered the `WAITING` state. A newly admitted worker still in `CREATED` is not counted, even if it has not acquired a space yet.
