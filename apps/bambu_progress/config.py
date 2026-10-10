"""printers.toml loading and validation."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_HOST = "10.0.4.20"

COLORS: dict[str, str] = {
    "bambu": "#00D455",   # Bambu Lab green, lifted for LEDs (#00AE42 reads dim); the default for every printer
    "mint": "#63E6BE",
    "amber": "#FFBF47",
    "blue": "#5096FF",
    "rose": "#FF5E93",
}
_COLOR_ORDER = list(COLORS)
DEFAULT_COLOR = "bambu"


class ConfigError(Exception):
    """Configuration is missing or invalid; message says where."""


@dataclass(frozen=True)
class PrinterConfig:
    name: str
    ip: str
    serial: str
    access_code: str
    color: str  # resolved "#RRGGBB"


LAYOUTS = ("list", "grid")   # list: 2 rows of 8px; grid: 2x2 cells of 36x8
MARKS = ("bambu", "printer")  # the mark drawn next to each name (icons.MARKS)


@dataclass(frozen=True)
class AppConfig:
    host: str
    token: str | None
    printers: list[PrinterConfig]
    layout: str = "list"
    mark: str = "bambu"


_REQUIRED = ("name", "ip", "serial", "access_code")


def _printer(index: int, raw: Any) -> PrinterConfig:
    if not isinstance(raw, dict):
        raise ConfigError(f"printers[{index}] must be a table")
    for key in _REQUIRED:
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"printers[{index}].{key} missing")
    color_name = raw.get("color", DEFAULT_COLOR)
    if color_name not in COLORS:
        raise ConfigError(
            f"printers[{index}].color must be one of {', '.join(_COLOR_ORDER)}, got {color_name!r}"
        )
    return PrinterConfig(
        name=raw["name"].strip(),
        ip=raw["ip"].strip(),
        serial=raw["serial"].strip(),
        access_code=raw["access_code"].strip(),
        color=COLORS[color_name],
    )


def parse_config(data: dict[str, Any]) -> AppConfig:
    busybar = data.get("busybar") or {}
    host = str(busybar.get("host") or DEFAULT_HOST)
    token_raw = busybar.get("token")
    token = str(token_raw) if token_raw else None

    raw_printers = data.get("printers")
    if not isinstance(raw_printers, list) or not raw_printers:
        raise ConfigError("config needs at least one printer ([[printers]])")
    printers = [_printer(i, raw) for i, raw in enumerate(raw_printers)]

    seen: dict[str, int] = {}
    for i, p in enumerate(printers):
        if p.serial in seen:
            raise ConfigError(
                f"printers[{i}] has duplicate serial {p.serial!r} (same as printers[{seen[p.serial]}])"
            )
        seen[p.serial] = i
    display = data.get("display") or {}
    layout = str(display.get("layout") or "list")
    if layout not in LAYOUTS:
        raise ConfigError(f"display.layout must be one of {', '.join(LAYOUTS)}, got {layout!r}")
    mark = str(display.get("mark") or "bambu")
    if mark not in MARKS:
        raise ConfigError(f"display.mark must be one of {', '.join(MARKS)}, got {mark!r}")
    return AppConfig(host=host, token=token, printers=printers, layout=layout, mark=mark)


def load_config(path: Path) -> AppConfig:
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    return parse_config(data)
