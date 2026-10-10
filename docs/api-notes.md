# BUSY Bar API 조사 노트 (2026-09-24)

## 1. 제품 개요
- 제조: Flipper Devices (Flipper Zero 팀). 오픈소스 생산성 타이머/상태 표시 기기.
- 앞면 72×16 RGB LED 매트릭스, 뒷면 160×80 16단계 그레이스케일 OLED.
- 펌웨어 오픈소스: https://github.com/busy-app/busybar-firmware (C, SCons `./fbt` 빌드)
- Matter 지원, Home Assistant 로컬 연동 가능 (클라우드 불필요).

## 2. 연결 방식 & 인증
| 경로 | 주소 | 인증 |
|---|---|---|
| USB | `http://10.0.4.20` (USB 이더넷 장치로 인식) | 없음 |
| Wi-Fi (LAN) | 기기 IP 또는 mDNS 검색 | 웹 UI에서 설정한 4~10자리 PIN. `403`이면 토큰 필요 |
| 클라우드 | `https://api.busy.app` | cloud.busy.app > API tokens 탭에서 발급 (1회만 표시) |

- 토큰 스코프: **BUSY Bar**(기기 제어) / **Account**(타이머 상태, 프로필).
- 헤더: `X-API-Token: <token>` (에뮬레이터 README에서 확인). busylib은 `token=` 인자로 처리.
- 기기 자체가 OpenAPI 3.1 문서를 서빙: `http://10.0.4.20/docs`, base URL `http://10.0.4.20/api`.
- 온라인 레퍼런스: https://api.busy.app/busybar/docs (기기 API), https://api.busy.app/docs (계정 API)

## 3. 공식 문서
- 개발 문서: https://docs.busy.app/bar/dev
- API 토큰: https://docs.busy.app/bar/dev/api-tokens
- 노코드 위젯: https://blog.busy.app/how-to-make-a-busy-bar-widget-without-coding/

## 4. 공식 SDK
### Python `busylib` (설치됨, 2.6.0)
- https://github.com/busy-app/busylib-py / 문서 https://busy-app.github.io/busylib-py/
- `BusyBar`(동기) / `AsyncBusyBar`(비동기), `BusyBarDevices.discover()`로 mDNS 검색.
- 주요 메서드: `version()`, `status()`, `display_draw()`, `display_clear()`,
  `display_brightness_set()`, `audio_play()`, `audio_stop()`, `audio_volume_set()`,
  `assets_upload()`, `storage_*`, `busy_snapshot()`(타이머), `stream_status_ws()`,
  `wifi_*`, `ble_*`, `smart_home_*`, `update_*`.
- 디스플레이 요소 타입: `TextElement`, `ImageElement`, `AnimationElement`,
  `CountdownElement`, `RectangleElement`. `display="front"|"back"`.
- 폰트: `tiny, small, normal, condensed, bold, large, extra_large, global, superscript`
- 정렬: `top_left, top_mid, top_right, mid_left, center, mid_right, bottom_left, bottom_mid, bottom_right`
- 색상: `#RRGGBBAA` 문자열 (API 25.0.0+) 또는 `[r,g,b]` 시퀀스.
- `DisplayElements(application_name, priority=1..100, elements=[...])`.
  같은 우선순위 충돌 시 HTTP **409** 반환. 앱은 재시도하면 됨.

### TypeScript `@busy-app/busy-lib`
- https://github.com/busy-app/busylib-ts
- `new BusyBar({ addr: '10.0.4.20' })`, `bar.SystemStatusGet()` 등 네임스페이스별 메서드
  (System, Display, Audio, Wifi, Storage, Settings, Ble, Input, SmartHome, Account, Assets, Time, Update).
- `StateStream`: WebSocket + protobuf 실시간 상태. `ScreenRenderer`: WebGL2로 화면 미러링 (브라우저 전용).
- Node.js에서는 HTTP 클라이언트만 사용 가능.

### 기타
- .NET 커뮤니티 라이브러리: https://busybar-dotnet.homotechsual.dev/
- Go 라이브러리 존재 (검색 결과 언급), JavaScript SDK는 "개발 중".

## 5. raw HTTP 예시 (SDK 없이)
```http
POST http://10.0.4.20/api/display/draw
Content-Type: application/json

{
  "application_name": "clock",
  "elements": [
    {"id": "0", "type": "text", "text": "12:34:56",
     "x": 36, "y": 15, "font": "extra_large",
     "color": "#FFFFFFFF", "align": "bottom_mid"}
  ]
}
```

## 6. 커뮤니티 생태계 (하드웨어 없이 개발 가능)
- **busybar-emulator**: https://github.com/maxswinkels/busybar-emulator
  펌웨어와 동일한 HTTP API/폰트/애니메이션 재현. Node 서버, `http://127.0.0.1:8080`.
  Draw 툴, preview.png/gif 캡처 기능 포함. 설치: `scripts/setup-emulator.sh`.
- **busybar-apps**: https://github.com/maxswinkels/busybar-apps
  커뮤니티 앱 갤러리. 앱 = 단일 `app.py` + `manifest.yaml` + 720×160 `preview.png`.
  `--host` 인자로 실기기/에뮬레이터 전환하는 관례.
- **busybar-manager**: https://github.com/maxswinkels/busybar-manager
  앱 실행/스케줄/자동시작 관리 대시보드 (`http://127.0.0.1:8321`).
- **busybar-lab**: https://github.com/subjektz3ro/busybar-lab
  uv 기반 앱 개발 템플릿, 오프라인 시각화(`busybar_viz`), dry-run.
- **hass-busybar**: https://github.com/pickerin/hass-busybar Home Assistant 통합.
- **busybar-web**: https://github.com/nconder/busybar-web 로컬 웹 콘솔.

## 7. 개발 시 주의
- 로컬 Python 3.9는 busylib 미지원 → 이 프로젝트는 Homebrew python3.12 venv 사용.
- 펌웨어 출고 버전 1.0.2(API 24.3.0)는 구형. 먼저 펌웨어 업데이트 권장 (SDK 타깃 27.5.0).
- 화면 밖 좌표의 요소는 그냥 렌더링되지 않음 (에러 없음).
