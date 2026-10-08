# Exploration: Implement Core API (Vehicle, ParkingLot, ParkingEvent, ParkingSnapshot)

## Exploration: Core concurrency module implementation

### Current State

- The repository is a **contract-first skeleton**. Every source module (`core/*`, `simulation/*`, `ui/*`, `main.py`) contains only a module docstring — no implementation exists yet.
- The authoritative API contract lives in `AGENTS.md` (root, sections 4, 5, 9) and is mirrored in `core/AGENTS.md`. It is team-approved and must not be invented or silently changed:
  - `core/events.py`: immutable `ParkingEvent` dataclass — `type: str, timestamp: float, vehicle_id: int | None = None, space_id: int | None = None, waiting_time: float | None = None`. Event types: `VEHICLE_CREATED`, `VEHICLE_WAITING`, `VEHICLE_ENTERED`, `VEHICLE_EXITED`, `VEHICLE_FINISHED`, `SIMULATION_STARTED`, `SIMULATION_FINISHED`.
  - `Vehicle(Thread)` receives `vehicle_id`, `parking`, `parking_duration`.
  - `ParkingLot(capacity: int, event_queue: Queue)` with `admit(vehicle) -> bool`, `snapshot() -> ParkingSnapshot`, `close(wait: bool = True) -> None`.
  - `ParkingSnapshot`: immutable copied read model with `capacity`, `occupied_count`, `waiting_count`, `occupied_spaces: tuple[tuple[int, int], ...]`.
  - `Semaphore` gates capacity; the caller thread never blocks waiting for a space; each `Vehicle` thread waits internally.
  - `Lock` protects shared mutable state (occupied spaces, assignment, counters).
  - `close()` rejects new admissions, cancels waiting vehicles, lets parked vehicles finish, optionally joins active threads; no forced thread termination.
  - Core emits vehicle lifecycle events only; `Simulator` owns `SIMULATION_STARTED`/`SIMULATION_FINISHED` (out of this change's scope).
- `simulation/` and `ui/` must be treated as **integration context only**: `Simulator` will call `admit()` and `close()`; the UI will consume events and may call `snapshot()`. This change must not touch them.
- `openspec/config.yaml` is initialized (`strict_tdd: false`, test command `python -m pytest`; pytest 8.3.4 available). `tests/` contains only `.gitkeep`. Branch is `main`; the team convention requires feature work on `feature/core` (section 13 of AGENTS.md).

### Affected Areas

- `core/events.py` — new: `ParkingEvent` dataclass (`frozen=True`) plus event-type constants; single source of the shared event contract.
- `core/vehicle.py` — new: `Vehicle(Thread)` with the CREATED → WAITING → PARKED → FINISHED state machine and internal wait on capacity.
- `core/parking.py` — new: `ParkingLot` (admission, space assignment, release, close policy) and `ParkingSnapshot` read model.
- `tests/` — new: unit/integration tests covering the seven correctness checks of AGENTS.md section 11 restricted to core behavior (items 1–5, 7; item 6 is UI-freeze, out of core scope).
- Not touched but coupled as contracts: `simulation/simulator.py` (admission loop, lifecycle events), `ui/interface.py` (queue consumer, `snapshot()` reads), `main.py` (composition).

### Concurrency Invariants (must hold regardless of design chosen)

1. `occupied_count <= capacity` at any observation point.
2. No `space_id` ever assigned to two live vehicles concurrently; each acquired space is released exactly once → semaphore `acquire`/`release` counts match.
3. Every admitted vehicle eventually reaches `FINISHED` (normally, or via close-cancel), so no thread leaks after `close(wait=True)`.
4. `waiting_count` and `occupied_count` are read only under the lock (snapshot consistency).
5. Admission after `close()` is rejected (`admit -> False`) and never blocks the caller.
6. Event ordering in the queue must reflect internal state transitions exactly: `CREATED` → `WAITING`/`VEHICLE_ENTERED` → `VEHICLE_EXITED` → `VEHICLE_FINISHED`; duplicate events or out-of-order parking (e.g., `ENTERED` after `FINISHED`) are contract violations.

### Approaches

The open design problem is **how a waiting `Vehicle` is unblocked when `close()` cancels it**, since `threading.Semaphore.acquire()` with no timeout cannot be interrupted from another thread.

1. **Closed flag + timed-acquire polling loop**
   - `Vehicle.run()` loops `acquire(timeout=ε)` while checking a `closed` event/flag under the lock; on `closed`, it aborts to FINISHED without parking.
   - Pros: simplest, no extra synchronization primitives, easy to test with small ε, acceptable academic complexity.
   - Cons: wakeup latency up to ε; polling loop is slightly wasteful; ε is a tunable that must live in core (not a magic number).
   - Effort: Low.

2. **Closed flag + close() releases one semaphore token per waiting vehicle**
   - `close()` counts waiters under the lock, marks closed, then `release()`s that many tokens; each vehicle re-checks the closed flag *under the lock after acquiring*, and if closed, releases immediately and finishes without occupying a space.
   - Pros: prompt unblocking without polling latency; keeps the Semaphore as the sole capacity gate.
   - Cons: requires careful post-acquire re-check to avoid a "phantom parking" after close (a re-acquired token must never be honored as a parking slot); release accounting must be exact to avoid inflating capacity for a future reopen (reopen is unlikely but the invariant "acquire/release match" must be argued explicitly).
   - Effort: Medium.

3. **Condition variable (with Lock) replacing the semaphore wait**
   - Capacity wait via `Condition.wait()` on a predicate; close `notify_all()`.
   - Pros: textbook OS blocking-wakeup pattern.
   - Cons: **violates the mandate** that `threading.Semaphore` gates capacity and that the waiting happen on the vehicle thread against the Semaphore; the project's academic objective forbids removing the Semaphore to solve this.
   - Effort: Medium — rejected as incompatible with the contract.

Space assignment design: either a fixed free-list (`list[bool]`/dict of space slots protected by the lock, vehicle gets the first free `space_id`) or an incrementing pointer with hole reuse. The free-list is recommended: it is what the UI's per-space rendering (`occupied_spaces` pairs) expects and makes "same space twice" trivially testable.

### Recommendation

**Approach 2** (close-releases-tokens + post-acquire re-check under lock), with the free-list space assignment. Rationale: no polling latency, the Semaphore remains the true capacity gate (pedagogically required), and the double-release hazard is contained by a single `closed` flag guarded by the same lock that does assignment. Fallback to Approach 1 only if the post-acquire re-check proves fragile in tests.

### Decision Gaps (orchestrator/user must decide — not assumed here)

1. **Event type for close-cancelled waiting vehicles**: AGENTS.md section 4 lists the 7 permitted types. Does a waiting vehicle that is cancelled by `close()` emit `VEHICLE_FINISHED`, or is a new type (e.g. `VEHICLE_CANCELLED`) needed? Adding a type is **a shared-contract change requiring team agreement and an AGENTS.md update** (section 12). This must be asked of the user before the spec is written.
2. **Waiting-time semantics**: `waiting_time` is only meaningful for `VEHICLE_ENTERED`; confirm that cancelled vehicles never carry it and that `VEHICLE_WAITING` carries none (present reading of the contract, but the spec phase should pin it down).
3. **Feature branch**: work must target `feature/core` per section 13 — confirm the orchestrator wants the branch created from `main` in this change's apply phase.

### Risks

- Emitting events from a vehicle thread after `close()` returns could touch the queue after the app tears down; event emission during shutdown ordering needs care (queue exists and is drained by the UI, but `close(wait=False)` may leave stragglers).
- `close(wait=True)` must never be called from a vehicle thread (self-join deadlock); this is an integration concern for `Simulator`/`main.py` that the design must document.
- Test flakiness: concurrency tests must use short, injected timings (seconds-scale params from `simulation/config.py` are too slow for tests); tests need their own tiny durations without reaching into internal magic numbers.
- Any change to event names/types ripples to `simulation/` and `ui/` — out of scope, contract change workflow of section 12 applies.

### Ready for Proposal

**Yes**, with one blocking question to the user first: what event (existing `VEHICLE_FINISHED` vs. a new contract-approved type) should a close-cancelled waiting vehicle emit. Once answered, the orchestrator can run `sdd-propose` for the change (suggested name: `implement-core-api`).
