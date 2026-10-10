"""SDK 없이 raw HTTP로 매초 시계를 그린다. (커뮤니티 앱 관례와 동일한 형태)"""
import json
import time
import urllib.error
import urllib.request

from _common import parse_host

args = parse_host("Clock via raw HTTP API")
URL = f"http://{args.host}/api/display/draw"


def draw(text: str) -> None:
    body = {
        "application_name": "clock",
        "elements": [
            {
                "id": "0",
                "type": "text",
                "text": text,
                "x": 36,
                "y": 15,
                "font": "extra_large",
                "color": "#FFFFFFFF",
                "align": "bottom_mid",
            }
        ],
    }
    req = urllib.request.Request(
        URL,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if args.token:
        req.add_header("X-API-Token", args.token)
    urllib.request.urlopen(req, timeout=5).read()


while True:
    try:
        draw(time.strftime("%H:%M:%S"))
    except urllib.error.HTTPError as e:
        if e.code != 409:  # 409 = 다른 앱이 화면 점유 중, 다음 초에 재시도
            raise
    time.sleep(1 - (time.time() % 1))
