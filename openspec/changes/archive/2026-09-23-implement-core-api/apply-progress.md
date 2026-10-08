# Apply Progress: Implement the Core Parking API

## Mode and Delivery

- Mode: Standard (`strict_tdd: false`); assigned RED tests were run before production changes in all three work units.
- Delivery: `auto-chain`, `feature-branch-chain`; work unit 1 is the immutable event contract (intended PR #1 base: `feature/core`). Work unit 2 is the capacity/snapshot API (intended PR #2 base: the PR #1 branch). Work unit 3 is shutdown/race handling (intended PR #3 base: the PR #2 branch); no commit or PR created.
- Scope of work unit 3: `core/parking.py`, `core/vehicle.py`, `tests/test_vehicle_lifecycle.py`, and this change's progress/tasks artifacts. No simulation, UI, main, or contract changes.

## Cumulative Task Status

- [x] 1.1 Add RED tests for frozen `ParkingEvent`, exact five fields/defaults, and the seven established event constants.
- [x] 1.2 Implement the frozen event dataclass and established constants and pass the focused event tests.
- [x] 1.3 Add RED lifecycle event assertions for normal immediate and waiting paths (production GREEN in work unit 2).
- [x] Phase 2: 2.1–2.5 capacity, admission, vehicle normal lifecycle, and snapshots.
- [x] Phase 3: 3.1–3.6 shutdown, queue publication, ordering, and race regressions.
- [x] Phase 4: 4.1–4.2 spec review, branch and scope handoff.

## Work Unit Evidence

| Evidence | Result |
|---|---|
| Focused test command and exact result | `python -m pytest tests/test_events.py`: RED before implementation, exit 1 (3 failed: missing model/constants); GREEN after implementation, exit 0 (3 passed in 0.13s). |
| Runtime harness command/scenario and exact result | N/A — this slice defines standalone event data and vocabulary; no runtime/UI boundary or event producer exists in the assigned scope. Actual queue emission and ownership must be checked with the later lifecycle implementation. |
| Rollback boundary | Revert only `core/events.py` and `tests/test_events.py` (event model and its contract tests); restore these two task checkboxes and remove this work-unit's progress record separately. No other production behavior is altered. |

### Work Unit 2: Capacity, normal lifecycle, and snapshots

| Evidence | Result |
|---|---|
| Focused test command and exact result | `python -m pytest tests/test_events.py tests/test_parking.py tests/test_vehicle_lifecycle.py`: RED before implementation, exit 2 (2 collection errors: `ParkingLot` missing); GREEN after implementation, exit 0 (10 passed in 1.05s). |
| Runtime harness command/scenario and exact result | N/A — core public API with threads and queue is exercised by the foreground pytest suite; no UI or simulator runtime boundary exists in this slice. |
| Rollback boundary | Restore scaffold `core/parking.py` and `core/vehicle.py`, remove `tests/test_parking.py` and `tests/test_vehicle_lifecycle.py`; retain `core/events.py` and `tests/test_events.py`. Restore task 1.3 and 2.1–2.5 checkboxes and this unit's progress record separately. |

The tests exercise admission while full, a CREATED scheduling gap, sorted immutable snapshots, waiting/entry/release, distinct owner IDs and normal queue event fields. Close currently only marks the lot closed and rejects new admissions; its `wait` argument is not yet honored and it cannot wake blocked waiters. Do not call close with outstanding waiters before work unit 3 adds wake-credit cancellation and joins. No threat-matrix cases apply (design matrix: N/A).

### Work Unit 3: Shutdown, cancellation, and race regression

| Evidence | Result |
|---|---|
| Focused test command and exact result | `python -m pytest tests/test_vehicle_lifecycle.py -q`: RED before implementation, exit 1 (5 failed, 2 passed; 1 unhandled-thread warning from the preexisting close race); GREEN after implementation, exit 0 (8 passed in 1.61s). `python -m pytest tests/test_vehicle_lifecycle.py tests/test_parking.py -q`: exit 0 (13 passed in 2.52s). |
| Runtime harness command/scenario and exact result | The foreground core runtime harness `python -m pytest tests/test_vehicle_lifecycle.py tests/test_parking.py -q` drove real vehicle threads, semaphore waits, paused post-acquire/pre-commit closure, CREATED-at-close and post-FINISHED/pre-return joins with bounded barriers: exit 0, 13 passed in 2.52s. UI/Simulator integration is not implemented in this scope and remains deferred. |
| Rollback boundary | Restore only work-unit-2 versions of `core/parking.py` and `core/vehicle.py`, and restore the pre-unit-3 content of `tests/test_vehicle_lifecycle.py`. Revert this unit's task checkboxes and progress section. Keep prior `core/events.py`, `tests/test_events.py`, and `tests/test_parking.py` work intact. |

Shutdown issues exactly one wake credit per registered WAITING vehicle at first close; every acquired-but-cancelled worker returns its permit before FINISHED. The final lifecycle drains issued credits once, after all parked holders and waiters have released permits. Repeated close issues none. `close(wait=True)` snapshots and joins every successfully started thread outside the lot lock, including the gap after FINISHED but before actual thread return; a lot-owned vehicle cannot self-join. CREATED workers delayed past close finish without waiting or acquiring. Events remain single-pass and queue-ordered under the lot lock.

Configured full test command `python -m pytest`: exit 0, 16 passed in 3.07s. Parent spot-check: exit 0, 16 passed in 3.11s. Focused contention/shutdown suite repeated separately: exit 0, 13 passed in 2.52s; lifecycle-only repeat: exit 0, 8 passed in 1.61s. The shutdown stress test itself runs 12 bounded contention/close rounds per invocation. Design threat matrix is N/A for external boundaries. Source scope reviewed against all three delta specs: only core and tests changed, alongside this change's task/progress files. Working branch `feature/core` was created from `main` with explicit user authorization; no commit, PR, or remote action was performed. PR #3 is planned to target the immediate PR #2 branch, not `main`.

## Limitations

Work unit 1 alone proved the approved shared vocabulary, not actual queue emission. Work unit 2 proved normal vehicle queue emission but left close incomplete at its phase boundary; work unit 3 now covers cancellation, shutdown and close races. No threat-matrix RED cases apply (design threat matrix: N/A). UI responsiveness and cross-module integration remain untested because UI/Simulator are outside this change.
