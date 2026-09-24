# Tasks: Implement the Core Parking API

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 350–500 authored changed lines across three core modules and focused tests |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1: immutable events and lifecycle tests → PR 2: capacity/snapshot API and tests → PR 3: shutdown/race behavior and integration tests |
| Delivery strategy | auto-chain |
| Chain strategy | feature-branch-chain |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

The implementation has multiple concurrency transitions and race regressions; splitting at event model, capacity lifecycle, and shutdown boundaries keeps each change independently reviewable. Auto-chain permits starting with the first slice. The selected `feature-branch-chain` uses `feature/core` as the tracker branch; PR #1 targets `feature/core`, PR #2 targets the PR #1 branch, and PR #3 targets the PR #2 branch. The user authorized creating `feature/core` from `main` before apply.

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1 | Establish immutable event contract and event tests | PR 1 (base: `feature/core`) | `python -m pytest tests/test_events.py` | `python -m pytest tests/test_events.py` exercises immutable payload fields and event vocabulary; no GUI/runtime harness is applicable | Revert `core/events.py` and `tests/test_events.py` only |
| 2 | Implement admission, capacity, exclusive spaces, waiting/reuse, and snapshots | PR 2 (base: PR #1 branch) | `python -m pytest tests/test_parking.py` | Run the focused parking tests with bounded thread joins; they drive concurrent admission and space reuse without external services | Revert `core/parking.py` and `tests/test_parking.py`, retaining the event-contract slice |
| 3 | Implement graceful shutdown, cancellation, event order, and race regressions | PR 3 (base: PR #2 branch) | `python -m pytest tests/test_vehicle_lifecycle.py tests/test_parking.py` | Run deterministic barrier-controlled close races through pytest; UI runtime is explicitly out of scope | Revert `core/vehicle.py` and `tests/test_vehicle_lifecycle.py`; retain independently valid event/capacity slices |

## Phase 1: Event Contract and RED Tests

- [x] 1.1 Add RED tests in `tests/test_events.py` for frozen `ParkingEvent`, exact five fields/defaults, and the seven approved event constants; verify core emits only vehicle lifecycle types and does not claim simulator event ownership.
- [x] 1.2 Implement the frozen event dataclass and approved constants in `core/events.py`; run `python -m pytest tests/test_events.py` to make the contract tests pass.
- [x] 1.3 Add RED event assertions in `tests/test_vehicle_lifecycle.py` for CREATED/ENTERED/EXITED/FINISHED field rules, nonnegative `waiting_time` only on ENTERED, and same-space ENTERED/EXITED pairing; leave lifecycle production behavior for later phases.

## Phase 2: Capacity, State Transitions, and Snapshots

- [x] 2.1 Add RED constructor/admission tests in `tests/test_parking.py` for positive capacity validation, accepted thread start, rejection after close, repeated admission rejection, wrong-lot ownership rejection, and thread-start failure rollback with no CREATED publication.
- [x] 2.2 Implement `ParkingSnapshot`, fixed space IDs, capacity semaphore, lock-owned state, and immutable copied snapshot in `core/parking.py`; assert `occupied_count == len(occupied_spaces)`, unique IDs, and `waiting_count` counts only vehicles that have entered WAITING (CREATED workers are excluded).
- [x] 2.3 Implement `Vehicle(Thread)` construction, state representation, immediate nonblocking permit attempt, and normal parked/exit lifecycle delegation in `core/vehicle.py`; add the corresponding GREEN checks in `tests/test_parking.py` and `tests/test_vehicle_lifecycle.py`.
- [x] 2.4 Add RED contention tests in `tests/test_parking.py` proving `admit` returns promptly when full, occupancy never exceeds capacity, waiting vehicles remain outside occupied counts, and a released space is eventually reused; then make them pass using semaphore-gated worker waits and lock-protected exclusive assignment.
- [x] 2.5 Add RED snapshot immutability/load tests in `tests/test_parking.py` and GREEN verification for fresh sorted tuple copies and consistent occupancy/waiting counts under repeated concurrent snapshots.

## Phase 3: Shutdown, Events, and Race Regressions

- [x] 3.1 Add RED shutdown tests in `tests/test_vehicle_lifecycle.py` for close rejecting admissions, cancelling registered waiters with `VEHICLE_FINISHED` (no new cancellation event), parked vehicles finishing naturally, repeated close, and `close(wait=False)` followed by `close(wait=True)`.
- [x] 3.2 Implement idempotent close, one-time wake-credit issuance for registered WAITING vehicles, post-acquire closed checks, cancelled permit return, and terminal wake-credit reconciliation in `core/parking.py`; verify no cancelled waiter enters and no permit is leaked or inflated.
- [x] 3.3 Add a deterministic RED regression in `tests/test_vehicle_lifecycle.py` that pauses a waiter after semaphore acquire but before it obtains the lot lock, closes the lot, then asserts FINISHED without ENTERED and verifies credits drain only after all accepted lifecycles terminate; implement the required synchronized transition in `core/parking.py`/`core/vehicle.py`.
- [x] 3.4 Add RED tests in `tests/test_vehicle_lifecycle.py` for a CREATED-but-not-yet-WAITING worker at close, `close(wait=True)` joining the retained admitted-thread set, and self-join rejection before close state changes; implement thread registration/start rollback and joins outside the lot lock.
- [x] 3.5 Assert per-vehicle single-pass normal order CREATED → optional WAITING → ENTERED → EXITED → FINISHED and cancellation order CREATED → optional WAITING → FINISHED in `tests/test_vehicle_lifecycle.py`; ensure publication occurs inside synchronized transitions through the supplied queue.
- [x] 3.6 Run `python -m pytest` and repeat bounded contention/shutdown regression cases; confirm core remains free of UI, Tkinter, simulation, and `main.py` edits, and report UI responsiveness as deferred integration verification.

## Phase 4: Review and Handoff

- [x] 4.1 Review `core/events.py`, `core/parking.py`, `core/vehicle.py`, and `tests/` against all three delta specs and the design threat matrix; no threat-matrix rows require RED tests because the matrix is explicitly N/A for external boundaries.
- [x] 4.2 Confirm only the authorized core/test scope changed and implementation stayed on the explicitly authorized `feature/core` branch created from `main`.
