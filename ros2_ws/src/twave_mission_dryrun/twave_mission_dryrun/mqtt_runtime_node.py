"""ROS 2 wrapper for :mod:`mqtt_runtime`, restricted to dry-run topics."""

from __future__ import annotations

import queue
from pathlib import Path

import paho.mqtt.client as mqtt
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from OCS import vehicle_protocol
from usv_main_fsm.audit_log import AuditLogger

from .mqtt_runtime import TWaveMqttRuntime
from .protocol import encode


MISSION_BASE = "/tongji_mrl/mission"


class TWaveMqttRuntimeNode(Node):
    """MQTT ingress/egress around MissionBridge; never a hardware adapter."""

    def __init__(self) -> None:
        super().__init__("twave_mqtt_runtime_dryrun")
        self.declare_parameter("dry_run", True)
        self.declare_parameter("broker_host", "127.0.0.1")
        self.declare_parameter("broker_port", 1883)
        self.declare_parameter("mqtt_username", "")
        self.declare_parameter("mqtt_password", "")
        self.declare_parameter("command_topic", vehicle_protocol.topic("T-Wave", "command"))
        self.declare_parameter("ack_topic", vehicle_protocol.topic("T-Wave", "ack"))
        self.declare_parameter("task_report_topic", vehicle_protocol.topic("T-Wave", "task_report"))
        self.declare_parameter("fault_topic", vehicle_protocol.topic("T-Wave", "fault"))
        self.declare_parameter("max_message_age_seconds", 300.0)
        self.declare_parameter("checkpoint_path", str(Path.home() / ".local/state/twave-mission/mqtt-checkpoint.json"))
        if self.get_parameter("dry_run").value is not True:
            raise RuntimeError("dry_run=false is forbidden by this package")
        self._inbound: queue.SimpleQueue[tuple[str, bytes]] = queue.SimpleQueue()
        self._mission_commands = {
            name: self.create_publisher(String, f"{MISSION_BASE}/{name}", 10)
            for name in ("run_start", "task4_cmd")
        }
        self.create_subscription(String, f"{MISSION_BASE}/status", self._status, 10)
        self.create_subscription(String, f"{MISSION_BASE}/task_report", self._task_report, 10)
        self.create_subscription(String, f"{MISSION_BASE}/fault", self._fault, 10)
        self.runtime = TWaveMqttRuntime(
            self.get_parameter("checkpoint_path").value, self._publish_mqtt, self._publish_dryrun,
            max_message_age_seconds=float(self.get_parameter("max_message_age_seconds").value),
            command_topic=str(self.get_parameter("command_topic").value),
            outbound_topics={
                "ack": str(self.get_parameter("ack_topic").value),
                "task_report": str(self.get_parameter("task_report_topic").value),
                "fault": str(self.get_parameter("fault_topic").value),
            },
        )
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        username = str(self.get_parameter("mqtt_username").value)
        if username:
            self.client.username_pw_set(username, str(self.get_parameter("mqtt_password").value))
        self.client.connect(str(self.get_parameter("broker_host").value), int(self.get_parameter("broker_port").value), keepalive=60)
        self.client.loop_start()
        self.create_timer(0.05, self._drain_mqtt)

    def destroy_node(self):
        self.client.loop_stop()
        self.client.disconnect()
        return super().destroy_node()

    def _on_connect(self, client, _userdata, _flags, reason_code, _properties=None) -> None:
        if reason_code == 0:
            client.subscribe(self.runtime.command_topic, qos=1)
            self.get_logger().info("connected to internal MQTT; subscribed to T-Wave commands")
        else:
            self.get_logger().error(f"MQTT connection failed: {reason_code}")

    def _on_disconnect(self, _client, _userdata, _flags, reason_code, _properties=None) -> None:
        self.get_logger().warning(f"MQTT disconnected: {reason_code}; reconnecting")

    def _on_message(self, _client, _userdata, message) -> None:
        self._inbound.put((message.topic, bytes(message.payload)))

    def _drain_mqtt(self) -> None:
        while not self._inbound.empty():
            topic, raw = self._inbound.get()
            try:
                self.runtime.receive(topic, raw)
            except Exception as exc:
                self.get_logger().error(f"rejected MQTT command on {topic}: {exc}")

    def _publish_mqtt(self, topic: str, raw: bytes) -> None:
        result = self.client.publish(topic, raw, qos=1, retain=False)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            self.get_logger().error(f"MQTT publish failed topic={topic}: {result.rc}")

    def _publish_dryrun(self, name: str, payload: dict) -> None:
        if name not in self._mission_commands:
            raise ValueError(f"unexpected mission command output: {name}")
        msg = String(); msg.data = encode(payload)
        self._mission_commands[name].publish(msg)

    def _status(self, msg: String) -> None:
        self._report("status", msg)

    def _task_report(self, msg: String) -> None:
        self._report("task_report", msg)

    def _fault(self, msg: String) -> None:
        self._report("fault", msg)

    def _report(self, name: str, msg: String) -> None:
        from .protocol import decode
        try:
            self.runtime.receive_mission_report(name, decode(msg.data))
        except Exception as exc:
            self.get_logger().error(f"rejected mission {name}: {exc}")


def main() -> None:
    rclpy.init()
    node = TWaveMqttRuntimeNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
