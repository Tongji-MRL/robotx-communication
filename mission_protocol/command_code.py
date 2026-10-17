"""Fixed three-bit mission command codes."""

COMMAND_CODES = {
    "NONE": "000",
    "ACK": "001",
    "REQUEST_PAUSE": "010",
    "REQUEST_RESUME": "011",
    "REPORT_TASK_COMPLETE": "100",
    "REPORT_TASK_FAILED": "101",
    "REQUEST_SAFE_HOLD": "110",
    "REQUEST_ABORT": "111",
}
