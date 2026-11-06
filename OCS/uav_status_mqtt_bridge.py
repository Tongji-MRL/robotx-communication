#!/usr/bin/env python3
"""Read-only ROS 2 UAV-status to internal-MQTT bridge, for Ubuntu only.

It relays the exact String payload after schema and explicit-ID validation.
It has no RoboCommand client and never constructs a Heartbeat or command.
"""
from __future__ import annotations

import argparse

import paho.mqtt.client as mqtt

from uav_status import normalize_uav_status
from vehicle_link import UAV_STATUS_TOPIC


def main() -> int:
    parser = argparse.ArgumentParser(description="Bridge read-only UAV ROS2 JSON to internal MQTT")
    parser.add_argument("--broker", default="192.168.112.1")
    parser.add_argument("--port", type=int, default=1884)
    parser.add_argument("--source-vehicle-id", required=True,
                        help="exact vehicle_id expected inside the ROS2 JSON")
    args = parser.parse_args()
    try:
        import rclpy
        from rclpy.node import Node
        from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
        from std_msgs.msg import String
    except ImportError as exc:
        raise SystemExit(f"ROS2/std_msgs is required on the Ubuntu bridge host: {exc}") from exc

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.reconnect_delay_set(min_delay=1, max_delay=10)
    client.connect_async(args.broker, args.port, keepalive=60)
    client.loop_start()

    class StatusBridge(Node):
        def __init__(self) -> None:
            super().__init__("robotx_uav_status_mqtt_bridge")
            qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE,
                             durability=DurabilityPolicy.VOLATILE)
            self.create_subscription(String, UAV_STATUS_TOPIC, self.on_status, qos)

        def on_status(self, message: String) -> None:
            try:
                # Validation is a gate only; the raw source JSON remains intact.
                normalize_uav_status(message.data, source_vehicle_id=args.source_vehicle_id)
                result = client.publish(UAV_STATUS_TOPIC, message.data, qos=1, retain=False)
                if result.rc != mqtt.MQTT_ERR_SUCCESS:
                    self.get_logger().error(f"internal MQTT publish rejected: rc={result.rc}")
            except Exception as exc:
                self.get_logger().warning(f"discarded UAV status: {exc}")

    rclpy.init(args=None)
    node = StatusBridge()
    node.get_logger().info(f"bridging {UAV_STATUS_TOPIC} to {args.broker}:{args.port}; read-only")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
        client.disconnect()
        client.loop_stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
