#!/usr/bin/env python3
"""Bridge the official RoboCommand link and the team vehicle MQTT link.

The gateway is intentionally thin:

* official RxCommand/RunStart is decoded by ``OcsClient``;
* queued commands are sent only to the USV mission coordinator;
* vehicle envelopes are passed back to ``OcsClient`` for protocol conversion;
* task selection and Task 4 arbitration remain inside the USV.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from ocs_client import (
    DEFAULT_CONFIG,
    OcsClient,
    config_values,
    declaration_values,
    load_config,
)
from vehicle_link import VehicleLink
from watchdog import OcsWatchdog


class OcsGateway:
    def __init__(
        self,
        *,
        official_broker: str,
        official_port: int,
        internal_broker: str,
        internal_port: int,
        team_id: str = "TONG",
        mission_coordinator: str = "T-Wave",
        state_path: str | Path | None = None,
        heartbeat_timeout_s: float = 3.0,
        command_ack_timeout_s: float = 5.0,
    ) -> None:
        self.ocs = OcsClient(
            official_broker,
            official_port,
            team_id=team_id,
            mission_coordinator=mission_coordinator,
            state_path=state_path,
        )
        self.watchdog = OcsWatchdog(heartbeat_timeout_s, command_ack_timeout_s)
        self.vehicle_link = VehicleLink(
            internal_broker,
            internal_port,
            on_message=self._accept_vehicle_envelope,
        )

    def _accept_vehicle_envelope(self, envelope: dict) -> None:
        self.ocs.accept_vehicle_envelope(envelope)
        kind = envelope.get("kind")
        vehicle_id = str(envelope.get("vehicle_id", ""))
        if kind == "heartbeat":
            self.watchdog.note_heartbeat(vehicle_id, time.monotonic())
        elif kind == "ack":
            payload = envelope.get("payload") or {}
            if payload.get("command_seq") is not None:
                self.watchdog.note_ack(int(payload["command_seq"]))

    def connect(self) -> None:
        self.ocs.connect()
        self.vehicle_link.connect()

    def publish_declaration(
        self,
        vehicle_ids: list[str],
        task_tiers: tuple[str, str, str, str],
        uav_geofence: list[tuple[float, float]],
    ) -> None:
        self.ocs.publish_run_declaration(vehicle_ids, task_tiers, uav_geofence)
        self.watchdog.start_run(vehicle_ids, time.monotonic())

    def flush_commands(self) -> None:
        for action in self.ocs.drain_internal_actions():
            if action.get("vehicle_id") != self.ocs.mission_coordinator:
                raise ValueError(
                    "OCS gateway refuses to send a command directly to a non-USV vehicle"
                )
            self.vehicle_link.send_action(action)
            command_seq = action.get("command_seq")
            if command_seq is not None:
                self.watchdog.note_command_sent(int(command_seq), time.monotonic())

    def run(self, duration: float = 0.0) -> None:
        deadline = time.monotonic() + duration if duration else None
        while deadline is None or time.monotonic() < deadline:
            self.flush_commands()
            for event in self.watchdog.check(time.monotonic()):
                print(json.dumps({"event": "watchdog_timeout", **event}, ensure_ascii=False))
            time.sleep(0.1)

    def close(self) -> None:
        self.vehicle_link.close()
        self.ocs.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OCS official RoboCommand ↔ USV coordinator gateway"
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--official-broker", help="computer B official broker")
    parser.add_argument("--official-port", type=int)
    parser.add_argument("--internal-broker", help="team internal broker")
    parser.add_argument("--internal-port", type=int, default=1883)
    parser.add_argument("--mission-coordinator", default="T-Wave")
    parser.add_argument("--state-path", type=Path, help="durable sequence state; default comes from config")
    parser.add_argument("--heartbeat-timeout", type=float, help="seconds without a vehicle heartbeat")
    parser.add_argument("--command-ack-timeout", type=float, help="seconds to wait for a vehicle ACK")
    parser.add_argument("--duration", type=float, default=0.0, help="0 means continuous")
    parser.add_argument(
        "--publish-declaration",
        action="store_true",
        help="publish the configured RunDeclaration after connecting",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    team_id, config_official_host, config_official_port, vehicles = config_values(config)
    internal_config = config.get("internal_broker", {})
    official_host = args.official_broker or config_official_host
    official_port = args.official_port or config_official_port
    internal_host = args.internal_broker or str(internal_config.get("host", "127.0.0.1"))
    internal_port = args.internal_port or int(internal_config.get("port", 1883))
    task_tiers, geofence = declaration_values(config)
    watchdog_config = config.get("watchdog", {})
    state_path = args.state_path or Path(config.get("state_path", "logs/ocs_state.json"))

    gateway = OcsGateway(
        official_broker=official_host,
        official_port=official_port,
        internal_broker=internal_host,
        internal_port=internal_port,
        team_id=team_id,
        mission_coordinator=args.mission_coordinator,
        state_path=state_path,
        heartbeat_timeout_s=args.heartbeat_timeout or float(watchdog_config.get("heartbeat_timeout_s", 3.0)),
        command_ack_timeout_s=args.command_ack_timeout or float(watchdog_config.get("command_ack_timeout_s", 5.0)),
    )
    try:
        gateway.connect()
        if args.publish_declaration:
            gateway.publish_declaration(vehicles, task_tiers, geofence)
        gateway.run(args.duration)
    except KeyboardInterrupt:
        pass
    finally:
        gateway.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
