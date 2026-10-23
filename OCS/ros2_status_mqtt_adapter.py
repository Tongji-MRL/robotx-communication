#!/usr/bin/env python3
"""Optional, read-only ROS 2 status-v2 to internal MQTT forwarder.

This is intentionally not part of the production bridge.  It subscribes only
to formal planner outputs and publishes normalized MQTT observation envelopes.
It never publishes ROS commands, changes the FSM, sets local_safety_ready, or
starts MAVROS/executors.  Importing this file on Windows does not require ROS.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

try:
    from .vehicle_protocol import encode, make_message, topic
except ImportError:
    from vehicle_protocol import encode, make_message, topic


def build_envelope(raw: str) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("schema_version") != "twave-mission-status-v2":
        raise ValueError("only formal twave-mission-status-v2 is forwarded")
    return make_message("T-Wave", "mission_status", value, run_id=value.get("run_id"), source="ros2-fsm-adapter")


def main() -> int:
    parser = argparse.ArgumentParser(description="OPTIONAL read-only FSM status ROS2->MQTT adapter")
    parser.add_argument("--enable", action="store_true", help="required; adapter otherwise does nothing")
    parser.add_argument("--broker", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--ros-topic", default="/tongji_mrl/mission/status")
    args = parser.parse_args()
    if not args.enable:
        print("Disabled: pass --enable only for an isolated integration environment.")
        return 0
    try:
        import paho.mqtt.client as mqtt
        import rclpy
        from rclpy.node import Node
        from std_msgs.msg import String
    except ImportError as exc:
        raise SystemExit("ROS 2 and paho-mqtt are required only when this optional adapter is enabled") from exc
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2); client.connect(args.broker, args.port); client.loop_start()
    class Adapter(Node):
        def __init__(self) -> None:
            super().__init__("ocs_readonly_status_adapter")
            self.create_subscription(String, args.ros_topic, self.callback, 10)
        def callback(self, msg: String) -> None:
            try:
                envelope = build_envelope(msg.data)
                client.publish(topic("T-Wave", "mission_status"), encode(envelope), qos=1)
            except (ValueError, json.JSONDecodeError) as exc:
                self.get_logger().warning(f"Rejected status: {exc}")
    rclpy.init(); node = Adapter()
    try: rclpy.spin(node)
    finally: node.destroy_node(); rclpy.shutdown(); client.loop_stop(); client.disconnect()
    return 0

if __name__ == "__main__": raise SystemExit(main())
