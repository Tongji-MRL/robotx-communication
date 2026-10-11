"""Small OCS configuration checker.

This is only the initial scaffold. It intentionally does not connect to an
official RoboCommand server or execute vehicle commands yet.
"""

import argparse
import json
from pathlib import Path


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def check_config(config: dict) -> list[str]:
    errors: list[str] = []

    team_id = config.get("team_id", "")
    if not team_id or team_id.startswith("REPLACE_"):
        errors.append("team_id 仍未填写官方最终 Team ID")

    broker = config.get("internal_broker", {})
    if not broker.get("host") or not broker.get("port"):
        errors.append("internal_broker.host/port 未填写")

    vehicles = config.get("vehicles", {})
    for domain in ("uav", "usv"):
        item = vehicles.get(domain, {})
        vehicle_id = item.get("vehicle_id", "")
        if not vehicle_id or vehicle_id.startswith(("ASSIGNED_BY_", "TBD")):
            errors.append(f"vehicles.{domain}.vehicle_id 未填写")
        if not item.get("orin_ip"):
            errors.append(f"vehicles.{domain}.orin_ip 未填写")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 OCS 初始配置")
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()

    config = load_config(args.config)
    errors = check_config(config)
    print(json.dumps(config, ensure_ascii=False, indent=2))

    if errors:
        print("配置检查结果：待补充")
        for error in errors:
            print(f"- {error}")
        return 1

    print("配置检查结果：通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
