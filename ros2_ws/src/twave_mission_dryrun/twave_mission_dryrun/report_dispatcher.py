"""Dispatch boundary for already-generated RoboCommand report protobufs."""

from __future__ import annotations

from dataclasses import dataclass

from .report_publisher import RxReportPublisher
from .rx_report_adapter import rx_reports_pb2


@dataclass(frozen=True)
class PreSendRecord:
    """Minimal immutable state recorded before handing a report to MQTT."""

    team_id: str
    vehicle_id: str
    seq: int


class ReportDispatcher:
    """Validate and record a generated RxReport before delegating publication."""

    def __init__(self, publisher: RxReportPublisher) -> None:
        self.publisher = publisher
        self.pre_send_records: list[PreSendRecord] = []

    def dispatch(self, report):
        if not isinstance(report, rx_reports_pb2.RxReport):
            raise TypeError("report must be an rx_reports_pb2.RxReport")
        self.pre_send_records.append(PreSendRecord(
            team_id=report.team_id, vehicle_id=report.vehicle_id, seq=report.seq,
        ))
        return self.publisher.publish(report)
