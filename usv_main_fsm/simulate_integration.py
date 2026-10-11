"""No-network, adapter-level T-Wave integration demonstrations."""

from __future__ import annotations

import argparse
from pathlib import Path

from .fake_integration import IntegrationHarness
from .models import TaskId


def run(scenario: str) -> list[str]:
    path = Path.cwd() / "usv_main_fsm" / ".integration-simulation-checkpoint.json"
    path.unlink(missing_ok=True)
    try:
        harness = IntegrationHarness(path)
        harness.ocs_command("run_start", run_id=42)
        if scenario == "normal":
            harness.complete(TaskId.TASK1, "task1-done")
            harness.uav.accept_delivery_request({
                "resource_color": "RED", "delivery_circle_color": "BLUE", "target_position": {"north_m": 1},
            }, scheduling_permitted=True)
            harness.log.append("UAV delivery request accepted after valid USV data")
            harness.complete(TaskId.TASK3, "task3-done")
        else:
            harness.ocs_command("task4_assistance", run_id=42)
            harness.complete(TaskId.TASK4, "task4-done")
            harness.dispatch(harness.coordinator.release_task4(42, recovery_permitted=True, vehicles_safe=True))
        harness.log.append(f"STATE {harness.coordinator.state.value}")
        return harness.log
    finally:
        path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="T-Wave phase-two fake protocol integration")
    parser.add_argument("scenario", choices=("normal", "task4"))
    args = parser.parse_args()
    print("\n".join(run(args.scenario)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
