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
        internal_command_topic: str | None = None,
        internal_subscription_topic: str | None = None,
        internal_username: str | None = None,
        internal_password: str | None = None,
    ) -> None:
        self.ocs = OcsClient(
            official_broker,
            official_port,
            team_id=team_id,
            mission_coordinator=mission_coordinator,
        )
        self.vehicle_link = VehicleLink(
            internal_broker,
            internal_port,
            on_message=self.ocs.accept_vehicle_envelope,
            command_topic=internal_command_topic,
            subscription_topic=internal_subscription_topic,
            username=internal_username,
            password=internal_password,
            on_connect=self.ocs.queue_course_sync,
        )

    def connect(self) -> None:
        self.ocs.connect()
        self.vehicle_link.connect()
        self.ocs.queue_course_sync()

    def publish_declaration(
        self,
        vehicle_ids: list[str],
        task_tiers: tuple[str, str, str, str],
        uav_geofence: list[tuple[float, float]],
    ) -> None:
        self.ocs.publish_run_declaration(vehicle_ids, task_tiers, uav_geofence)

    def flush_commands(self) -> None:
        for action in self.ocs.drain_internal_actions():
            if action.get("vehicle_id") != self.ocs.mission_coordinator:
                raise ValueError(
                    "OCS gateway refuses to send a command directly to a non-USV vehicle"
                )
            if action.get("kind") == "course_config":
                self.vehicle_link.send_course_config(action)
            else:
                self.vehicle_link.send_action(action)

    def run(self, duration: float = 0.0) -> None:
        deadline = time.monotonic() + duration if duration else None
        next_heartbeat = time.monotonic()
        while deadline is None or time.monotonic() < deadline:
            self.flush_commands()
            if time.monotonic() >= next_heartbeat:
                self.ocs.publish_cached_heartbeats()
                next_heartbeat = time.monotonic() + 0.5
            time.sleep(0.1)

    def close(self) -> None:
        self.vehicle_link.close()
        self.ocs.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OCS official RoboCommand to USV coordinator gateway"
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--official-broker", help="computer B official broker")
    parser.add_argument("--official-port", type=int)
    parser.add_argument("--internal-broker", help="team internal broker")
    parser.add_argument("--internal-port", type=int, default=1883)
    parser.add_argument("--mission-coordinator", default="T-Wave")
    parser.add_argument("--internal-command-topic", help="T-Wave internal command topic")
    parser.add_argument("--internal-subscription-topic", help="internal vehicle report subscription filter")
    parser.add_argument("--internal-username", help="internal MQTT username")
    parser.add_argument("--internal-password", help="internal MQTT password")
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

    gateway = OcsGateway(
        official_broker=official_host,
        official_port=official_port,
        internal_broker=internal_host,
        internal_port=internal_port,
        team_id=team_id,
        mission_coordinator=args.mission_coordinator,
        internal_command_topic=args.internal_command_topic,
        internal_subscription_topic=args.internal_subscription_topic,
        internal_username=args.internal_username,
        internal_password=args.internal_password,
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
