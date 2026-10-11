"""MQTT publication boundary for already-built RoboCommand ``RxReport`` messages."""

from __future__ import annotations

from typing import Any, Protocol

from .rx_report_adapter import rx_reports_pb2


TOPIC_ROOT = "robocommand/robotx"


class MqttPublisher(Protocol):
    """The small subset of the existing Paho client used for up-link reports."""

    def publish(self, topic: str, payload: bytes, *, qos: int, retain: bool) -> Any: ...


class RxReportPublisher:
    """Serialize and publish reports; it owns neither MQTT connection nor protobuf creation."""

    def __init__(self, client: MqttPublisher) -> None:
        self.client = client

    @staticmethod
    def topic_for(report) -> str:
        if not isinstance(report, rx_reports_pb2.RxReport):
            raise TypeError("report must be an rx_reports_pb2.RxReport")
        if not report.team_id or not report.vehicle_id:
            raise ValueError("report team_id and vehicle_id are required")
        return f"{TOPIC_ROOT}/{report.team_id}/{report.vehicle_id}/report"

    def publish(self, report):
        """Serialize one RxReport and hand it to an already-connected MQTT client."""
        topic = self.topic_for(report)
        return self.client.publish(topic, report.SerializeToString(), qos=1, retain=False)
