# Core Commit Stabilization

## Objective
Stabilize the core test suite and commit the completed core implementation as reviewable work units.

## Problem
The core implementation is present in the working tree, but the snapshot concurrency test is timing-sensitive and can fail before a stable parked/waiting state is observed. Commits must not be created until verification is stable.

## Why
The core module demonstrates OS concepts through threads, semaphores, locks, and shared-resource coordination. The commit history should preserve coherent review units without freezing flaky tests.

## Scope
- Stabilize `tests/test_parking.py::test_snapshots_are_frozen_sorted_copies_under_load`.
- Verify the focused test repeatedly and the full suite once stable.
- Commit the core changes as work units:
  1. Event contract.
  2. Vehicle admission and capacity coordination.
  3. Shutdown and waiting-vehicle cancellation.
  4. OpenSpec documentation/archive, subject to review-size budget.

## Constraints
- Do not change the shared event contract unexpectedly.
- Do not remove threads, semaphores, or locks.
- Keep Tkinter out of `core/`.
- Keep generated caches out of commits.

## Delivery strategy
- Strategy: `ask-on-risk`.
- Current note: `openspec/` is large enough to consider a separate PR/slice later.

## Tasks
- [x] CORE-COMMIT-001 — Inspect current repository status and confirm no commits/staged changes exist.
  - Route: inline verification.
  - Evidence: `git status --short --branch` showed uncommitted core, tests, and OpenSpec changes on `feature/core`.
- [x] CORE-COMMIT-002 — Stabilize the snapshot concurrency test.
  - Route: inline one-file test change.
  - Checks: `for i in 1 2 3 4 5; do python -m pytest tests/test_parking.py::test_snapshots_are_frozen_sorted_copies_under_load || exit 1; done` passed 5/5; `python -m pytest` passed 16/16.
- [x] CORE-COMMIT-003 — Commit event contract work unit.
  - Route: inline staging/commit.
  - Checks: `python -m pytest tests/test_events.py` passed 3/3.
  - Commit: `e152358 feat(core): add immutable parking event contract`.
- [x] CORE-COMMIT-004 — Commit coordinated vehicle/parking lifecycle work unit.
  - Route: inline staging/commit.
  - Checks: `python -m pytest tests/test_parking.py tests/test_vehicle_lifecycle.py` passed 13/13; `python -m pytest` passed 16/16.
  - Commit: `8c5c6c2 feat(core): implement threaded parking coordination`.
- [x] CORE-COMMIT-005 — Preserve shutdown/cancellation coverage inside the coherent core work unit.
  - Route: included in CORE-COMMIT-004 because `ParkingLot` admission, waiting, close, and semaphore reconciliation form one coupled protocol in the current implementation.
  - Checks: shutdown and race tests in `tests/test_vehicle_lifecycle.py` passed as part of 13/13 and 16/16 runs.
- [x] CORE-COMMIT-006 — Decide and prepare OpenSpec documentation commit/slice.
  - Route: inline status/diff review.
  - Checks: `git ls-files --others --exclude-standard | xargs wc -l` showed `openspec/` at 1266 lines; committed separately from core implementation.
  - Commit: `7cb5b3f docs(openspec): archive core api implementation specs`.
  - Review note: OpenSpec should be considered for a separate PR/slice because it exceeds the 400-line review budget by itself.

## Engram mirror
Pending: Engram write failed because the runtime reported multiple active sessions for this project/directory. Preserve this file as the source of truth until the mirror can be synchronized.

## Current next step
Run final repository checks and decide whether to push/open review slices.
