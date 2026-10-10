"""Steady Clock: a clock whose digits never shift.

The device's extra_large font is proportional (digits 7px, '1' 4px, ':' 2px), so a centred
"HH:MM:SS" string jumps left/right whenever a 1 appears. This app draws every glyph in its own
fixed slot instead.

    python -m apps.steady_clock.app                 # USB bar
    python -m apps.steady_clock.app --no-seconds --color "#63E6BEFF"
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

from busylib import BusyBar, exceptions

from apps.bambu_progress.app import configure_logging

APP = "steady-clock"
DIGIT_W = 7      # measured on the bar (extra_large font)
ONE_W = 4
COLON_W = 2
SLOT = DIGIT_W + 1
COLON_SLOT = COLON_W + 2
SCREEN_W = 72
TIME_Y = 8

log = logging.getLogger("steady-clock")


def _slot_width(ch: str) -> int:
    return COLON_SLOT if ch == ":" else SLOT


def layout_x(text: str) -> int:
    total = sum(_slot_width(ch) for ch in text)
    return (SCREEN_W - total) // 2


def elements_for(text: str, color: str) -> list[dict]:
    """One text element per glyph, each anchored mid_left in a fixed-width slot."""
    y = TIME_Y
    x = layout_x(text)
    elements: list[dict] = []
    for i, ch in enumerate(text):
        if ch == ":":
            gx = x + 1
        elif ch == "1":
            gx = x + (DIGIT_W - ONE_W) // 2
        else:
            gx = x
        elements.append({"id": f"t{i}", "type": "text", "text": ch, "x": gx, "y": y,
                         "font": "extra_large", "color": color, "align": "mid_left"})
        x += _slot_width(ch)
    return elements


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="steady-clock", description="Clock with fixed digit slots (no jitter)")
    p.add_argument("--host", default="10.0.4.20")
    p.add_argument("--token", default=None)
    p.add_argument("--no-seconds", action="store_true", help="show HH:MM only")
    p.add_argument("--color", default="#FFFFFFFF", help="#RRGGBBAA")
    p.add_argument("--once", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main() -> None:
    args = parse_args()
    configure_logging(args.verbose)
    fmt = "%H:%M" if args.no_seconds else "%H:%M:%S"
    bar = BusyBar(args.host, token=args.token, timeout=5)
    last_text = None
    try:
        while True:
            now = time.localtime()
            text = time.strftime(fmt, now)
            if text != last_text:
                try:
                    bar.display_draw({"application_name": APP, "priority": 50,
                                      "elements": elements_for(text, args.color)})
                    last_text = text
                except exceptions.BusyBarAPIError as exc:
                    if exc.status_code != 409:
                        log.warning("draw failed: %s", exc)
                except exceptions.BusyBarError as exc:
                    log.warning("bar unreachable: %s", exc)
                    time.sleep(3)
            if args.once:
                return
            time.sleep(max(0.05, 1.0 - (time.time() % 1)))
    except KeyboardInterrupt:
        pass
    finally:
        try:
            bar.display_clear(application_name=APP)
        except Exception:  # noqa: BLE001
            pass
        bar.close()
        print("stopped", file=sys.stderr)


if __name__ == "__main__":
    main()
