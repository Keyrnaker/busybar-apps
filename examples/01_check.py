"""연결 확인: 버전과 상태를 출력한다."""
from busylib import BusyBar

from _common import parse_host

args = parse_host("Check BUSY Bar connection")

with BusyBar(args.host, token=args.token) as bb:
    v = bb.version()
    print(f"Connected. API {v.api_semver or 'unknown'}")
    print(bb.status())
