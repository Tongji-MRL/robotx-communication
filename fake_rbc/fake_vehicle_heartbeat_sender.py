"""Explicit lab-only producer for the Windows OCS heartbeat ingress.

It emits only simulated telemetry and has no import-time network side effect.
``--execute-lab`` plus an explicit isolated broker are required to publish.
"""
from __future__ import annotations

import argparse
import json
import time
import uuid
from typing import Iterable


HEARTBEAT_TOPICS = {
    "T-Wave": "/tongji_mrl/twave/heartbeat",
    "T-Sky": "/tongji_mrl/tsky/heartbeat",
}


def heartbeat_payload(vehicle_id: str, *, run_id: int | None, now_ms: int | None = None,
                      message_id: str | None = None) -> dict:
    """Build raw JSON accepted by the production OCS receive boundary."""
    if vehicle_id not in HEARTBEAT_TOPICS:
        raise ValueError("vehicle_id must be T-Wave or T-Sky")
    timestamp = int(time.time() * 1000) if now_ms is None else now_ms
    vehicle_type = "uav" if vehicle_id == "T-Sky" else "usv"
    payload = {
        "source_mode": "simulation", "state": "AUTO", "vehicle_type": vehicle_type,
        "position": {"frame_id": "wgs84", "latitude_deg": 1.2806142,
                     "longitude_deg": 103.8557120, "altitude_hae_m": 0.0},
        "speed_mps": 0.0, "heading_deg": 0.0, "roll_deg": 0.0, "pitch_deg": 0.0,
        "health": {"fcu_connected": True, "simulator": True},
        "run_id": run_id, "message_id": message_id or str(uuid.uuid4()),
        "sent_at_unix_ms": timestamp,
    }
    if vehicle_type == "uav":
        payload["flight_phase"] = "grounded"
    return payload


def selected_vehicles(value: str) -> tuple[str, ...]:
    if value == "both":
        return ("T-Wave", "T-Sky")
    if value in HEARTBEAT_TOPICS:
        return (value,)
    raise ValueError("vehicle must be T-Wave, T-Sky, or both")


def publish_samples(client, vehicles: Iterable[str], *, run_id: int | None,
                    frequency_hz: float, duration_s: float) -> int:
    """Publish a finite sequence only after explicit lab opt-in."""
    deadline, period, count = time.monotonic() + duration_s, 1.0 / frequency_hz, 0
    while time.monotonic() < deadline:
        for vehicle_id in vehicles:
            raw = json.dumps(heartbeat_payload(vehicle_id, run_id=run_id),
                             ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            info = client.publish(HEARTBEAT_TOPICS[vehicle_id], raw, qos=1, retain=False)
            info.wait_for_publish(timeout=5.0)
            if not info.is_published() or info.rc != 0:
                raise RuntimeError(f"unable to publish {vehicle_id}: rc={info.rc}")
            count += 1
        time.sleep(period)
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="LAB ONLY: simulated OCS heartbeat ingress")
    parser.add_argument("--execute-lab", action="store_true", help="explicitly allow MQTT publishing")
    parser.add_argument("--broker", help="required isolated test broker host; no default target")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--vehicle", choices=("T-Wave", "T-Sky", "both"), default="both")
    parser.add_argument("--run-id", type=int, help="active test run_id; omit only without an active Gateway run")
    parser.add_argument("--frequency-hz", type=float, default=2.0)
    parser.add_argument("--duration-s", type=float, default=10.0)
    args = parser.parse_args()
    if not args.execute_lab:
        print("[DRY-RUN] Nothing sent. Add --execute-lab with an explicit isolated --broker.")
        return 0
    if not args.broker:
        parser.error("--broker is required with --execute-lab")
    if args.run_id is not None and args.run_id <= 0:
        parser.error("--run-id must be positive")
    if not 0.1 <= args.frequency_hz <= 10:
        parser.error("--frequency-hz must be within [0.1, 10]")
    if not 0 < args.duration_s <= 300:
        parser.error("--duration-s must be within (0, 300]")

    import paho.mqtt.client as mqtt
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                         client_id=f"robotx-fake-heartbeat-{uuid.uuid4().hex[:8]}")
    client.connect(args.broker, args.port, keepalive=30)
    client.loop_start()
    try:
        count = publish_samples(client, selected_vehicles(args.vehicle), run_id=args.run_id,
                                frequency_hz=args.frequency_hz, duration_s=args.duration_s)
        print(f"[DONE] published {count} explicitly simulated heartbeat sample(s)")
        return 0
    except KeyboardInterrupt:
        print("[STOPPED] no further heartbeat samples will be published")
        return 130
    finally:
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    raise SystemExit(main())
