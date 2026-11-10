"""Read-only receiver for the explicit localhost-only RunStart forwarding test.

It never imports vehicle, MAVLink, PX4, action, or waypoint code and only
subscribes to the dedicated offline test topic.
"""
from __future__ import annotations

import argparse
import json
import os


TOPIC = "/tongji_mrl/offline_test/run_start"
READY_TOPIC = "/tongji_mrl/offline_test/receiver_ready"


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only isolated OCS RunStart test receiver")
    parser.add_argument("--wait", type=float, default=45.0)
    parser.add_argument("--token", required=True, help="ephemeral token supplied to the offline gateway")
    args = parser.parse_args()
    if os.environ.get("ROS_DOMAIN_ID") != "62" or os.environ.get("ROS_LOCALHOST_ONLY") != "0":
        parser.error("requires ROS_DOMAIN_ID=62 and ROS_LOCALHOST_ONLY=0")
    if len(args.token) < 16:
        parser.error("--token must have at least 16 characters")
    try:
        import rclpy
        from rclpy.node import Node
        from std_msgs.msg import String
    except ImportError as exc:
        print(f"[UNAVAILABLE] ROS 2 Python runtime is required for this receiver: {exc}", flush=True)
        return 3
    rclpy.init(args=None)
    node = Node("robotx_offline_runstart_receiver")
    received = {"value": False}

    def callback(message: String) -> None:
        try:
            payload = json.loads(message.data)
            required = (payload.get("test_only") is True and isinstance(payload.get("official_team_id"), str)
                        and type(payload.get("official_command_seq")) is int
                        and type(payload.get("declaration_seq")) is int and type(payload.get("run_id")) is int)
            if not required:
                raise ValueError("missing required validated RunStart fields")
            print("[ROS2_RECEIVED] test_only=true team_id={official_team_id} command_seq={official_command_seq} declaration_seq={declaration_seq} run_id={run_id}".format(**payload), flush=True)
            received["value"] = True
        except Exception as exc:
            print(f"[ROS2_REJECTED] {exc}", flush=True)

    node.create_subscription(String, TOPIC, callback, 10)
    ready = String()
    ready.data = json.dumps({
        "kind": "offline_test_receiver_ready", "token": args.token,
        "read_only": True, "actuation": False, "topic": TOPIC,
    }, separators=(",", ":"))
    ready_pub = node.create_publisher(String, READY_TOPIC, 10)
    node.create_timer(0.25, lambda: ready_pub.publish(ready))
    print(f"[READY] Read-only receiver subscribed: {TOPIC}; capability published on {READY_TOPIC}", flush=True)
    try:
        deadline = node.get_clock().now().nanoseconds + int(args.wait * 1_000_000_000)
        while rclpy.ok() and not received["value"] and node.get_clock().now().nanoseconds < deadline:
            rclpy.spin_once(node, timeout_sec=0.2)
    finally:
        node.destroy_node()
        rclpy.shutdown()
    return 0 if received["value"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
