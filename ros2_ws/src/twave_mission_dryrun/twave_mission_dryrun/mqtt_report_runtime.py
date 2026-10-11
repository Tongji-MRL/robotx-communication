"""Lifecycle owner for the MQTT client used by the RxReport up-link only."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .report_publisher import RxReportPublisher


def _paho_client() -> Any:
    """Create the same Paho callback-v2 client style used by existing runtime code."""
    import paho.mqtt.client as mqtt

    return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)


class MqttReportRuntime:
    """Own connection lifecycle while leaving report serialization to Publisher."""

    def __init__(
        self,
        *,
        host: str,
        port: int = 1883,
        username: str = "",
        password: str = "",
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        if not host:
            raise ValueError("host is required")
        if not isinstance(port, int) or isinstance(port, bool) or port <= 0:
            raise ValueError("port must be a positive integer")
        self.host = host
        self.port = port
        self.client = (client_factory or _paho_client)()
        if username:
            self.client.username_pw_set(username, password)
        self.publisher = RxReportPublisher(self.client)
        self._connected = False

    def connect(self) -> None:
        """Connect the provided client and start its background network loop."""
        self.client.connect(self.host, self.port, keepalive=60)
        self.client.loop_start()
        self._connected = True

    def close(self) -> None:
        """Stop a previously-started network loop and close the broker connection."""
        if not self._connected:
            return
        self.client.loop_stop()
        self.client.disconnect()
        self._connected = False
