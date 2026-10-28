"""Headless academic scenario runner.

Runs one declared scenario (simulation.scenarios) through the real
multiprocessing engine and IPC transport, with no Tkinter/ui dependency.
This is a manual demonstration/smoke tool, not the application entry
point (see main.py for the real UI-driven entry point).
"""

from __future__ import annotations

import argparse
import sys

from simulation.audit_logging import AuditSession
from simulation.multiprocess import MultiprocessController
from simulation.scenarios import build_payload, list_scenarios


def main() -> int:
    names = [scenario.name for scenario in list_scenarios()]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=names)
    parser.add_argument("--timeout", type=float, default=15.0,
                        help="seconds to wait for each IPC message")
    args = parser.parse_args()

    payload = build_payload(args.scenario)
    audit = AuditSession()
    controller = MultiprocessController(payload["config"]["capacity"], audit=audit)
    exit_code = 0
    try:
        controller.start_engine()
        run_id = controller.start(payload)
        print(f"run {run_id} started: {payload['config']}")
        while True:
            message = controller.get(timeout=args.timeout)
            kind = message.get("kind")
            if kind == "event":
                print(f"EVENT  {message['name']:<20} {message['payload']}")
                if message["name"] == "SIMULATION_FINISHED":
                    break
            elif kind == "failure":
                print(f"FAILURE {message}", file=sys.stderr)
                exit_code = 1
                break
            elif kind == "audit":
                continue
            else:
                print(f"OTHER  {message}")
    finally:
        controller.shutdown()
        audit.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
