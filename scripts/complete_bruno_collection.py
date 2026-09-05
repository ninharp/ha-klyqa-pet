"""Complete the Klyqa Pet Bruno collection (OpenCollection YAML).

Usage: .venv/bin/python scripts/complete_bruno_collection.py "<input.yml>" "<output.yml>"

Adds missing requests, fixes stale URLs, attaches docs and response examples built from the
library fixtures (which mirror real device responses).
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

import yaml

FIXTURES = Path(__file__).resolve().parent.parent / "tests_lib" / "fixtures"
URL = "{{device_address}}:{{device_port}}/api/v1/"


class LiteralDumper(yaml.SafeDumper):
    """Dump multi-line strings as literal blocks, like Bruno does."""


def _str_presenter(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


LiteralDumper.add_representer(str, _str_presenter)


def fixture(name: str) -> str:
    """Load a device fixture and re-serialize it as pretty-printed JSON."""
    return json.dumps(json.loads((FIXTURES / name).read_text()), indent=2)


SUCCESS = json.dumps({"type": "success"}, indent=2)
ERROR = json.dumps({"type": "error", "error": ["Invalid request"]}, indent=2)


def example(
    name: str, status: int, body: str, method: str = "GET", path: str = ""
) -> dict[str, Any]:
    """Build one OpenCollection response example."""
    return {
        "name": name,
        "request": {"url": f"{URL}{path}", "method": method, "headers": [], "params": []},
        "response": {
            "status": status,
            "statusText": "OK" if status == 200 else "Bad Request",
            "headers": [{"name": "Content-Type", "value": "application/json"}],
            "body": {"type": "json", "data": body},
        },
    }


def request_item(
    name: str,
    method: str,
    path: str,
    seq: int,
    body: str | None = None,
    docs: str = "",
    examples: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build one OpenCollection HTTP request item."""
    http: dict[str, Any] = {"method": method, "url": f"{URL}{path}"}
    if body is not None:
        http["body"] = {"type": "json", "data": body}
    item: dict[str, Any] = {
        "info": {"name": name, "type": "http", "seq": seq},
        "http": http,
        "settings": {"encodeUrl": True, "timeout": 0, "followRedirects": True, "maxRedirects": 5},
    }
    if docs:
        item["docs"] = docs
    if examples:
        item["examples"] = examples
    return item


def find_folder(items: list[dict[str, Any]], *names: str) -> dict[str, Any]:
    """Descend into nested `items` by folder/request name."""
    node: dict[str, Any] = {"items": items}
    for name in names:
        node = next(i for i in node["items"] if i.get("info", {}).get("name") == name)
    return node


def walk(items: list[dict[str, Any]]) -> Any:
    """Yield every item in the tree, folders and requests alike."""
    for item in items:
        yield item
        if "items" in item:
            yield from walk(item["items"])


def main() -> None:
    """Complete the Bruno collection given as argv[1] and write it to argv[2]."""
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    collection = yaml.safe_load(src.read_text())
    items = collection["items"]

    # 1. Fix stale URLs: device/test -> device/debug (Welly), mark purifier Pet Tag folder.
    for item in walk(items):
        url = item.get("http", {}).get("url", "")
        if url.endswith("/device/test"):
            item["http"]["url"] = url.replace("/device/test", "/device/debug")
            item["docs"] = (
                "Pass-through to the MCU (development builds). The firmware registers this at "
                "`POST device/debug`; `device/test` no longer exists.\n\n" + item.get("docs", "")
            )
    purifier_tags = find_folder(items, "Klyqa Airpurifier", "Pet Tag")
    purifier_tags["docs"] = (
        "Not available on fw-klyqa-airpurifier: the purifier firmware only registers "
        "`device/state`. Kept for reference (Welly/Foody offer these actions)."
    )
    control_light = find_folder(items, "Klyqa Airpurifier", "State", "Set Control Light")
    control_light["http"]["body"]["data"] = '{\n  "type": "request",\n  "pl_switch": 1\n}'
    control_light["docs"] = "Switches the control-panel light (`pl_switch`, 0/1)."

    # 2. Add missing requests.
    purifier_state = find_folder(items, "Klyqa Airpurifier", "State")["items"]
    purifier_state += [
        request_item(
            "Set LED Brightness",
            "POST",
            "device/state",
            11,
            '{\n  "type": "request",\n  "brightness": {"percentage": 50}\n}',
            "LED ring brightness in percent (0-100).",
            [example("Success", 200, SUCCESS, "POST", "device/state")],
        ),
        request_item(
            "Set Panel Light Brightness",
            "POST",
            "device/state",
            12,
            '{\n  "type": "request",\n  "pl_brightness": 30\n}',
            "Brightness of the control-panel light (0-100).",
        ),
        request_item(
            "Set AQI Light",
            "POST",
            "device/state",
            13,
            '{\n  "type": "request",\n  "aqil_switch": 1\n}',
            "Air-quality indicator light on/off (`aqil_switch`, 0/1).",
        ),
        request_item(
            "Set Sleep Brightness",
            "POST",
            "device/state",
            14,
            '{\n  "type": "request",\n  "slp_bright": 30\n}',
            "Panel brightness while in night/sleep mode (0-100).",
        ),
        request_item(
            "Set Filter Info",
            "POST",
            "device/state",
            15,
            '{\n  "type": "request",\n  "fid": "F123",\n  "filter_type": 1,\n'
            '  "ftotal_tm": 259200,\n  "fremain_tm": 259200\n}',
            "Register a new filter: id, type and total/remaining minutes. "
            "Use after a filter change to reset the remaining life.",
        ),
    ]
    get_purifier_state = find_folder(items, "Klyqa Airpurifier", "State", "Get State")
    get_purifier_state["examples"] = [
        example("Purifier state", 200, fixture("airpurifier_state.json"))
    ]
    get_purifier_state["docs"] = (
        "Fields: `status` on/off, `p_level` fan level 0-3, `run_mode` 0 standalone/1 auto/"
        "2 night/3 pet, `aqi` grade 0 excellent-3 heavy, `aqi_num` µg/m³, `les` on = custom "
        "LED colour, `color{red,green,blue}`, `brightness{percentage}`, `anion_switch`/"
        "`anion_state` ionizer, `child_lock`, `key_tone`, `fremain_tm`/`ftotal_tm` filter "
        "minutes, `tilt_status`, `fremoval_status`, `wifi_parameters{rssi,security,channel}`."
    )

    welly = find_folder(items, "Klyqa Welly")["items"]
    welly.append(
        request_item(
            "Get Debug Info",
            "GET",
            "device/debug",
            20,
            None,
            "Heap statistics and internal counters (development builds only).",
        )
    )
    foody = find_folder(items, "Klyqa Foody")["items"]
    foody += [
        request_item(
            "Get Debug Info",
            "GET",
            "device/debug",
            20,
            None,
            "Heap statistics and internal counters (development builds only).",
        ),
        request_item(
            "Send Raw MCU Command",
            "POST",
            "device/debug",
            21,
            '{\n  "cmd": 4,\n  "data_hex": "0105"\n}',
            "Development builds: send a raw feeder protocol packet (`cmd` id, payload as hex).",
        ),
    ]
    general = find_folder(items, "Klyqa General")["items"]
    general.append(
        request_item(
            "Health Check",
            "GET",
            "_health",
            8,
            None,
            "Internal watchdog endpoint, no Authorization header required.",
            [example("Alive", 200, '{\n  "status": "ok"\n}')],
        )
    )
    reboot = find_folder(items, "Klyqa General", "Commands", "Send Reboot")
    reboot["docs"] = (
        "Generic reboot for every device type (used by the Home Assistant integration)."
    )
    reboot["examples"] = [example("Success", 200, SUCCESS, "PUT", "system/command")]

    # 3. Response examples for GET requests from the fixtures.
    get_examples = {
        ("Klyqa Welly", "State", "Get State"): fixture("welly_state.json"),
        ("Klyqa Welly", "Settings", "Get Settings"): fixture("welly_settings.json"),
        ("Klyqa Foody", "State", "Get State"): fixture("foody_state.json"),
        ("Klyqa Foody", "Settings", "Get Settings"): fixture("foody_settings.json"),
        ("Klyqa General", "Get System Information"): fixture("system_info.json"),
    }
    for path, body in get_examples.items():
        find_folder(items, *path)["examples"] = [example("Example response", 200, body)]

    # 4. Representative error example on every POST/PUT that has none.
    for item in walk(items):
        method = item.get("http", {}).get("method")
        if method in ("POST", "PUT") and "examples" not in item:
            rel = item["http"]["url"].split("/api/v1/")[-1]
            item["examples"] = [
                example("Success", 200, SUCCESS, method, rel),
                example("Rejected", 400, ERROR, method, rel),
            ]

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(
        yaml.dump(collection, Dumper=LiteralDumper, sort_keys=False, allow_unicode=True, width=120)
    )
    print(f"wrote {dst}")


if __name__ == "__main__":
    main()
