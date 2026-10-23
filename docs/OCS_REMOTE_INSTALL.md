# Remote control computer installation

Copy `OCS` and `scripts`, install `OCS/requirements.txt`, then run
`scripts\start_monitor_readonly.bat --broker <internal-broker-ip>`.
The default server address is `127.0.0.1`; no ROS, MAVROS, propulsion, or
vehicle executor is started. `start_monitor_lab.bat` enables diagnostic MQTT
only for an isolated test network and must not bypass the formal FSM/Gateway.

Formal status visibility requires a verified production Bridge extension, or
the optional adapter on a ROS host. The optional adapter is not an Orin
deployment validation claim.
