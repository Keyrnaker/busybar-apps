# bambu-progress: BUSY Bar용 Bambu Lab 프린터 진행 상태 앱 설계

- 날짜: 2026-09-24
- 상태: 승인 대기
- 위치: `busybar/apps/bambu-progress/`

## 1. 목적과 범위

같은 LAN에 있는 Bambu Lab 프린터 3대의 출력 상태를 BUSY Bar 앞면(72×16 RGB LED)에
보여준다. 다이얼로 프린터를 고르고, 선택한 프린터의 진행률과 남은 시간을 진행바로 본다.
어느 프린터든 완료·일시정지·에러가 발생하면 화면과 소리로 알린다.

- 실행 환경: BUSY Bar를 USB로 연결한 Mac. 프린터와 같은 네트워크.
- 읽기 전용. 프린터에 명령을 보내지 않는다(개발자 모드 불필요).
- 클라우드 계정 불필요. 프린터 IP, 시리얼, LAN 액세스 코드만 사용.
- 하드웨어 없이 에뮬레이터와 `--demo` 모드로 전체 흐름을 볼 수 있어야 한다.

범위 밖: 프린터 제어(일시정지/재개), 카메라, 뒷면 디스플레이, 클라우드 API, 3대 초과 최적화.

## 2. 기술 사실 (조사 결과)

### Bambu 로컬 MQTT
- `mqtts://{ip}:8883`, TLS(자체 서명 인증서, 검증 생략), 사용자 `bblp`, 비밀번호 = LAN 액세스 코드.
- 구독 `device/{serial}/report`, 요청 `device/{serial}/request`.
- 접속 직후와 5분마다 pushall 요청:
  `{"pushing": {"sequence_id": "0", "command": "pushall", "version": 1, "push_target": 1}}`
- P1/A1 계열은 바뀐 값만 보낸다(델타). X1 계열은 전체를 보낸다. 항상 이전 상태에 병합한다.
- 사용하는 `print` 필드: `gcode_state`(IDLE/PREPARE/RUNNING/PAUSE/FINISH/FAILED),
  `mc_percent`(0~100), `mc_remaining_time`(분), `subtask_name`, `print_error`(0이면 정상),
  `hms`(목록, 각 항목 `attr`, `code`), `layer_num`, `total_layer_num`.
- 공식 위키: 펌웨어 인증 강화 이후에도 MQTT 상태 푸시는 인증 없이 동작한다.

### BUSY Bar
- busylib 2.6.0 (`AsyncBusyBar`). 그리기 `display_draw(DisplayElements)`, 지우기 `display_clear`,
  아이콘 업로드 `assets_upload(application_name, filename, data)`, 소리 `audio_play(stock_path=...)`,
  입력 스트림 `stream_status_ws()`.
- 입력 이벤트: 스트림 메시지의 `updates[].input.encoder_event.delta`(다이얼),
  `updates[].input.button_event.button`(ok/back/start, action이 비었거나 press일 때).
- 요소 타입: text(font: tiny/small/normal/condensed/bold/large/extra_large), image(path 또는 stock_path),
  rectangle. 색상 `#RRGGBBAA`. `priority` 1~100, 충돌 시 HTTP 409.
- 스톡 사운드: `shared/sounds/calendar_event_starts.snd`(event),
  `shared/sounds/calendar_reminder_ends.snd`(reminder).
- 에뮬레이터(maxswinkels/busybar-emulator)는 draw/assets upload/audio/status ws를 지원하지만
  스톡 이미지 이름 체계가 기기와 다르다. 따라서 이미지 아이콘은 전부 업로드한 커스텀 아이콘만 쓴다.

## 3. 화면 설계

프린터마다 강조색을 설정한다. 기본 팔레트: `mint #63E6BE`, `amber #FFBF47`, `blue #5096FF`,
`rose #FF5E93`. 회색 계열: 텍스트 `#A8B2C3`, 비활성 `#495365`, 트랙 `#2A3140`.
상태색: 완료 초록 `#3DDC84`, 일시정지 노랑 `#FFD23F`, 에러 빨강 `#FF4D4D`, 오프라인 `#495365`.

### 3.1 목록 화면 (`list`)
2줄, 줄 높이 8px. 선택한 줄은 강조색, 나머지는 회색.
```
x: 0-7 아이콘 | 9-  이름(small) | 우측 정렬: 상태 아이콘 6x6 + 퍼센트(small)
```
- 선택 줄이 항상 보이도록 창(window) 시작 = `selected // 2 * 2`.
- 다이얼 delta로 `selected = (selected + delta) % n`.
- 상태 표시: RUNNING → 노즐 애니메이션 2프레임 + `67%`, PREPARE → 모래시계 + `PREP`,
  PAUSE → 일시정지 아이콘 + 퍼센트(노랑), FINISH → 체크 + `DONE`(초록), FAILED/에러 → 에러 아이콘 + `ERR`(빨강),
  IDLE → `·`(회색), OFFLINE/STALE/AUTH ERR → X 아이콘 + `OFF`/`STALE`/`AUTH`(어두운 회색).
- OK → 선택 프린터 `detail`. BACK → `hidden`(display_clear). `hidden`에서 아무 버튼 → `list`.

### 3.2 상세 화면 (`detail`)
```
y 0-6 : x0-7 프린터 아이콘(강조색) | x9- 이름(small, 흰색) | 우측 정렬 퍼센트(bold, 강조색)
y 8-12: tiny, 회색. RUNNING "1h 12m left" (1시간 미만 "12m left", 분 미만 "<1m left")
y 13-15: 진행바. 트랙 x0-71 회색, 채움 폭 = round(72 * percent / 100), 강조색
```
- FINISH: 아이콘 → 체크(초록), 퍼센트 `100%`, 둘째 줄 작업명 스크롤(`scroll_rate`), 진행바 초록.
- PAUSE: 진행바 노랑, 1초 주기 점멸(채움 알파 FF↔60), 둘째 줄 `PAUSED`.
- FAILED 또는 print_error≠0 또는 hms에 에러 등급: 아이콘 → 에러(빨강), 둘째 줄 HMS 코드 스크롤, 진행바 빨강.
- PREPARE: 둘째 줄 `preparing…`, 진행바 회색 트랙만.
- IDLE: 둘째 줄 `idle`, 진행바 없음. 오프라인 계열: 둘째 줄 `offline` / `no data` / `bad access code`.
- BACK → `list`. 다이얼 → 다음/이전 프린터 `detail`로 직접 전환.

### 3.3 알림 오버레이 (`notice`)
어느 화면에서든, 어느 프린터든 전환 이벤트가 나면 덮어쓴다. 우선순위는 본 화면(50)보다 높은 80.
```
배경 rectangle 72x16 (상태색, 알파 FF) | x2 아이콘 8x8 | x12 "P1S-A" (bold) | 둘째 줄 tiny 메시지
```
| 이벤트 | 배경 | 아이콘 | 메시지 | 소리 | 지속 |
|---|---|---|---|---|---|
| FINISH 전환 | 초록 | 체크 | `DONE` | event | 8초 |
| PAUSE 전환 | 노랑 | 일시정지 | `PAUSED` | reminder | 8초 |
| 필라먼트 소진 HMS | 노랑 | 일시정지 | `FILAMENT` | reminder | 8초 |
| FAILED / print_error≠0 | 빨강 | 에러 | `ERROR` 또는 HMS 코드 | event | 버튼 누를 때까지 |

- 알림 중 다이얼·버튼 입력은 알림 해제로만 쓰고 원래 화면에 전달하지 않는다.
- 알림이 겹치면 큐에 넣고 순서대로 보여준다. 같은 프린터의 같은 이벤트는 중복 제거.
- 종료 후 이전 화면으로 복귀. `hidden` 상태였다면 다시 `hidden`.

### 3.4 아이콘
코드 안의 문자열 비트맵(`#`=칠함, `.`=투명)으로 정의하고 시작 시 PNG로 변환해 업로드한다.
색은 그릴 때 정하지 않고 아이콘 자체를 흰색으로 만들며, 색이 필요한 아이콘은 색별로 별도 파일을 올린다
(image 요소는 색 지정이 없으므로). 필요한 파일: 프린터(강조색 4종 + 회색), 노즐 애니메이션 2프레임
(강조색 4종), 체크(초록), 일시정지(노랑), 에러(빨강), 모래시계(회색), X(회색). 약 20개, 각 8×8 또는 6×6.
파일명은 `{icon}_{color}.png`. 업로드는 `assets_upload(application_name="bambu-progress", ...)`.
이미 올라간 파일은 `storage_list`로 확인해 건너뛴다(에뮬레이터는 매번 올린다).

## 4. 구성요소

단일 프로세스, asyncio. 모듈별 책임:

| 모듈 | 책임 | 의존 |
|---|---|---|
| `app.py` | 인자·설정 로드, 태스크 조립, 종료 시 display_clear | 전체 |
| `config.py` | `printers.toml` 파싱·검증, `PrinterConfig` | tomllib |
| `bambu.py` | `PrinterState` 데이터클래스, `parse_report(prev, payload) -> PrinterState`, `PrinterMonitor`(aiomqtt 접속·구독·pushall·재접속) | aiomqtt |
| `events.py` | `detect(prev, new) -> list[Event]` 순수 함수 | 없음 |
| `ui.py` | `Ui` 상태기계(screen, selected, notice 큐), `parse_input_events(message)` | render |
| `render.py` | `render_list`, `render_detail`, `render_notice` → `DisplayElements`. 색상표, 레이아웃 상수, 시간 포맷 | busylib.types |
| `icons.py` | 비트맵 정의, `to_png(bitmap, rgb) -> bytes`, `ensure_uploaded(bar)` | zlib, struct |
| `demo.py` | `DemoMonitor`: 시나리오대로 `PrinterState`를 흘려보냄 | bambu |

데이터 흐름:
```
PrinterMonitor×3 ─┐                          ┌─ InputLoop (stream_status_ws)
                  ├─ asyncio.Queue[Update] ─► Ui ─► render_* ─► AsyncBusyBar.display_draw
DemoMonitor×3   ──┘        │
                    events.detect ─► Ui.notice 큐 ─► audio_play
```
- `Update = (printer_index, PrinterState)`. Ui가 큐를 소비하며 `states[i]` 갱신, `events.detect(prev, new)` 호출.
- 그리기는 `dirty` 플래그 + 0.5초 틱으로 합쳐 초당 최대 2회. 애니메이션(노즐 토글, 점멸)도 이 틱에서 처리.
- `PrinterState` 필드: `name, connection(CONNECTING/ONLINE/STALE/OFFLINE/AUTH_ERROR), gcode_state, percent,
  remaining_min, task_name, print_error, hms_codes, layer, total_layers, last_report_at`.

설정 `printers.toml`:
```toml
[busybar]
host = "10.0.4.20"       # --host 가 우선
token = ""               # Wi-Fi 접속 시 PIN

[[printers]]
name = "P1S-A"
ip = "192.168.0.31"
serial = "01P00A123456789"
access_code = "12345678"
color = "mint"           # mint | amber | blue | rose
```
CLI: `python app.py [--host H] [--config printers.toml] [--demo] [--once]`.
`--demo`는 설정 파일 없이 가짜 3대로 동작. `--once`는 한 프레임 그리고 종료(스크린샷용).

## 5. 에러 처리

- MQTT 접속 실패/끊김: 해당 프린터 `OFFLINE`, 2초→4→8→…→최대 60초 백오프 재접속. 나머지는 영향 없음.
- 60초 동안 리포트 없음: `STALE`. 새 리포트가 오면 `ONLINE`.
- 인증 실패(CONNACK 5 / not authorized): `AUTH_ERROR`로 표시하고 재접속하지 않는다.
  잘못된 코드로 반복 접속하면 프린터가 잠길 수 있다.
- 첫 pushall 응답 전: `CONNECTING`.
- 리포트 JSON 파싱 실패: 로그만 남기고 무시.
- BUSY Bar 409: 무시하고 다음 틱에 재시도. 연결 오류: 5초 후 재시도, 터미널 로그. 알림 소리 실패는 무시.
- 설정 오류: 필수 필드 누락, 색 이름 오류, 중복 시리얼을 잡아 `printers[1].access_code missing` 형식으로 출력 후 종료 코드 2.
- Ctrl-C: 모니터 취소, `display_clear(application_name)` 시도 후 종료.

## 6. 테스트

- pytest, 네트워크 없음:
  - `parse_report`: 전체 리포트, 델타 병합, 필드 누락, 잘못된 타입.
  - `events.detect`: RUNNING→FINISH, RUNNING→PAUSE, →FAILED, print_error 0→n, 필라먼트 HMS, 동일 상태 반복 시 이벤트 없음, OFFLINE→ONLINE 시 이벤트 없음.
  - `render_*`: 각 상태에서 요소 개수·좌표·색·텍스트, 진행바 폭(0/50/100%), 시간 포맷, 목록 창 계산.
  - `icons.to_png`: 유효한 PNG 헤더와 크기.
  - `parse_input_events`: home-assistant 앱과 같은 메시지 형태.
  - `Ui`: 입력에 따른 화면 전환, 알림 큐 순서와 중복 제거.
- 수동: `--demo --host 127.0.0.1:8080` 으로 에뮬레이터에서 목록·상세·알림 세 가지 모두 확인.
  시나리오: 1번 진행→완료, 2번 진행→일시정지→재개, 3번 진행→에러. 약 60초.
- 실기기: USB 연결, 실제 프린터 1대 이상으로 상태 반영 확인.

## 7. 의존성

- Python 3.12 (`.venv`), `busylib>=2.6`, `aiomqtt>=2`, dev: `pytest`, `pytest-asyncio`.
- 실행 스크립트는 프로젝트 루트 `requirements.txt`에 추가.

## 8. 갤러리 제출 (후속)

커뮤니티 갤러리는 단일 `app.py`를 선호한다. 모듈 구조로 먼저 완성하고, 제출 시 하나로 합치는 스크립트를
별도로 만든다. `manifest.yaml`과 720×160 `preview.png`는 에뮬레이터 캡처로 만든다. 이 스펙의 범위 밖.
