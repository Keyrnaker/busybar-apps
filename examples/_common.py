"""예제 공용: --host 인자 파싱. 기본은 USB 주소, 에뮬레이터는 127.0.0.1:8080."""
import argparse
import os


def parse_host(description: str = "BUSY Bar example") -> argparse.Namespace:
    p = argparse.ArgumentParser(description=description)
    p.add_argument(
        "--host",
        default=os.environ.get("BUSYBAR_HOST", "10.0.4.20"),
        help="device address (default 10.0.4.20; emulator 127.0.0.1:8080)",
    )
    p.add_argument(
        "--token",
        default=os.environ.get("BUSYBAR_TOKEN"),
        help="access PIN / API token (Wi-Fi or cloud only)",
    )
    return p.parse_args()
