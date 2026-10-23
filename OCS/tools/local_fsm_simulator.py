#!/usr/bin/env python3
"""Publish explicitly simulated formal FSM status-v2 data to localhost MQTT only.

No ROS 2, Orin, task executor, command topic, Task4Guard file, or safety
authorization is used. This is a monitor-test publisher, not an FSM emulator.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OCS_ROOT = Path(__file__).resolve().parents[1]
if str(OCS_ROOT) not in sys.path:
    sys.path.insert(0, str(OCS_ROOT))
from vehicle_protocol import encode, make_message, topic  # noqa: E402

LOCAL_BROKERS = {"127.0.0.1", "localhost", "::1"}
SCENARIOS = ("WAIT_COURSE", "COURSE_ACCEPTED", "WAIT_RUN_START", "TASK1_ACTIVE", "TASK3_ACTIVE", "TASK4_WAITING", "TASK4_PAUSED", "FAULT", "DISCONNECTED")


def _vehicle(task: str | None = None, progress: str | None = None, error: str | None = None) -> dict[str, Any]:
    return {"vehicle": "", "current_task": task, "progress": progress, "ended": False,
            "error": error, "error_code": "NONE" if not error else "SIMULATED_FAULT",
            "error_severity": "INFO" if not error else "STOP",
            "recommended_action": "NONE" if not error else "SAFE_STOP",
            "safety_state": "SIMULATION", "detail": "simulation only"}


def status_for(scenario: str) -> dict[str, Any]:
    """Return status-v2 using only formal FSM state/safety names from source."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario: {scenario}")
    fsm, run_id, accepted, uav_applied = "WAIT_FOR_BEGIN", None, False, False
    safety, recovery = "WAITING_FOR_LOCAL_SAFETY", ["local_safety_ready"]
    usv, uav = _vehicle(), _vehicle()
    if scenario in {"COURSE_ACCEPTED", "WAIT_RUN_START"}:
        accepted = True
    elif scenario == "TASK1_ACTIVE":
        fsm, run_id, safety, recovery = "TASK1_EXECUTE", 202601, "READY", []
        usv, uav = _vehicle("TASK1", "TASK1_ACTIVE"), _vehicle("TASK1", "TASK1_ACTIVE")
    elif scenario == "TASK3_ACTIVE":
        fsm, run_id, safety, recovery = "TASK3_EXECUTE", 202601, "READY", []
        usv, uav = _vehicle("TASK3", "TASK3_ACTIVE"), _vehicle("TASK3", "TASK3_ACTIVE")
    elif scenario in {"TASK4_WAITING", "TASK4_PAUSED"}:
        # Formal code remains in the interrupted MAP/TASK1/TASK3 state until
        # Task4Guard has both pause ACKs and checkpoints. It has no TASK4_WAITING enum.
        fsm, run_id = "TASK3_EXECUTE", 202601
        safety, recovery = "WAITING_SAFE_PAUSE", ["pause_ack_uav", "pause_ack_usv", "checkpoint_uav", "checkpoint_usv"]
        progress = "PAUSED" if scenario == "TASK4_PAUSED" else None
        usv, uav = _vehicle("TASK3", progress), _vehicle("TASK3", progress)
    elif scenario == "FAULT":
        fsm, run_id, safety = "FAILED", 202601, "SAFE_STOP"
        recovery = ["explicit_safety_recovery_authorization"]
        usv, uav = _vehicle("TASK3", "TASK3_ACTIVE", "SIMULATED_CRITICAL_FAULT"), _vehicle("TASK3", "TASK3_ACTIVE")
    course = {"loaded": accepted, "applied": accepted, "fsm_accepted": accepted,
              "uav_applied": uav_applied,
              "uav_application_state": "CONFIRMED" if uav_applied else "NOT_CONFIRMED",
              "course_id": "SIM-COURSE-LOCAL" if accepted else None,
              "fingerprint": "simulation-only-not-a-course-fingerprint" if accepted else None}
    usv["vehicle"], uav["vehicle"] = "usv", "uav"
    legacy = {"mission_planner": fsm, "uav": {"task": uav["current_task"], "progress": uav["progress"], "error": uav["error"]}, "usv": {"task": usv["current_task"], "progress": usv["progress"], "error": usv["error"]}}
    return {**legacy, "schema_version": "twave-mission-status-v2", "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "fsm_state": fsm, "course": course, "safety": {"state": safety, "recovery_conditions": recovery},
            "vehicles": {"uav": uav, "usv": usv}, "legacy": legacy,
            "simulation": True, "simulation_scenario": scenario}


def heartbeat(vehicle_id: str, vehicle_type: str) -> dict[str, Any]:
    return {"source_mode": "simulation", "simulation": True, "vehicle_type": vehicle_type,
            "state": "SIMULATION", "position": {"frame_id": "wgs84", "latitude_deg": 0.0, "longitude_deg": 0.0, "altitude_hae_m": 0.0},
            "speed_mps": 0.0, "heading_deg": 0.0, "roll_deg": 0.0, "pitch_deg": 0.0, "health": {"simulation": True}}


def publish_once(client: Any, scenario: str) -> bool:
    if scenario == "DISCONNECTED":
        return False
    payload = status_for(scenario)
    envelope = make_message("T-Wave", "mission_status", payload, run_id=payload["run_id"], source="local-fsm-simulator")
    client.publish(topic("T-Wave", "mission_status"), encode(envelope), qos=1).wait_for_publish()
    for vehicle_id, kind in (("T-Wave", "usv"), ("T-Sky", "uav")):
        client.publish(topic(vehicle_id, "heartbeat"), encode(make_message(vehicle_id, "heartbeat", heartbeat(vehicle_id, kind), source="local-fsm-simulator")), qos=1).wait_for_publish()
    if scenario == "FAULT":
        client.publish(topic("T-Wave", "fault"), encode(make_message("T-Wave", "fault", {"simulation": True, "error": "SIMULATED_CRITICAL_FAULT"}, source="local-fsm-simulator")), qos=1).wait_for_publish()
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Local-only simulation publisher for OCS monitor")
    parser.add_argument("--broker", default="127.0.0.1", choices=sorted(LOCAL_BROKERS))
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--scenario", choices=SCENARIOS, default="TASK1_ACTIVE")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--count", type=int, default=1, help="0 publishes until interrupted; DISCONNECTED publishes nothing")
    args = parser.parse_args()
    try:
        import paho.mqtt.client as mqtt
    except ImportError as exc:
        raise SystemExit("paho-mqtt is required: python -m pip install -r OCS\\requirements.txt") from exc
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(args.broker, args.port, keepalive=10); client.loop_start()
    try:
        attempts = published = 0
        while args.count == 0 or attempts < args.count:
            published += int(publish_once(client, args.scenario)); attempts += 1
            if args.count == 0 or attempts < args.count: time.sleep(max(args.interval, .1))
    finally:
        client.loop_stop(); client.disconnect()
    print(json.dumps({"simulation": True, "scenario": args.scenario, "published": published, "broker": args.broker}))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
