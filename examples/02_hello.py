"""앞면 72x16 LED에 텍스트를 그린다."""
from busylib import BusyBar, types

from _common import parse_host

APP = "hello"
args = parse_host("Draw hello text on the front display")

with BusyBar(args.host, token=args.token) as bb:
    bb.display_draw(
        types.DisplayElements(
            application_name=APP,
            elements=[
                types.TextElement(
                    id="msg",
                    text="HELLO",
                    font="large",
                    x=36,
                    y=8,
                    align="center",
                    color="#00FF88FF",
                    timeout=10,  # 10초 후 자동 제거
                )
            ],
        ),
        clear_before_draw=True,
    )
    print("drawn")
