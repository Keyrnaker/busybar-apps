# BUSY Launcher: 맥 메뉴바 런처 설계

- 날짜: 2026-09-24
- 위치: `busybar/launcher/` (Swift), 결과물 `BUSY Launcher.app`
- 상태: 구현됨 (2026-09-25). 실기기 검증은 docs/superpowers/plans/2026-09-24-busy-launcher.md Task 13 참고

## 1. 목적

맥 메뉴바에 BUSY 아이콘 하나를 두고, 거기서 앱을 고르면 그 앱이 BUSY Bar에 뜬다.
앱은 이 저장소의 `apps/` 에 직접 만든 것과 커뮤니티 갤러리(maxswinkels/busybar-apps)에서 내려받은 것 모두.
한 번에 하나만 실행. 배포 가능한 단일 `.app` 이어야 하며, 받는 사람 맥에 Python이 없어도 동작한다.

범위 밖: 로그인 자동 시작(사용자가 직접 관리), 여러 앱 동시 실행과 우선순위, 스케줄, 기기 펌웨어 JS 앱.

## 2. 사용자에게 보이는 것

### 메뉴바
- 아이콘: 템플릿 이미지(모노크롬) BUSY 마크. 실행 중인 앱이 있으면 아이콘 우하단에 점.
- 클릭 시 메뉴:
  1. 상태 줄(비활성): `BUSY Bar · USB 연결됨` / `연결 안 됨` / `Wi-Fi 192.168.x.x`
  2. 앱 목록: 아이콘 + 이름. 실행 중인 앱은 체크 표시. 죽은 앱은 이름 뒤 `(중단됨)`.
     클릭 → 그 앱 시작(이미 실행 중인 다른 앱은 정지). 실행 중인 앱 클릭 → 정지.
  3. 구분선, `갤러리에서 설치…`, `앱 폴더 열기`, `로그 보기`, `설정…`, `새로고침`, 구분선, `종료 ⌘Q`.
- 메뉴는 열 때마다 앱 폴더를 다시 스캔한다(앱 추가·삭제가 즉시 반영).

### 설정 창 (일반 창, 3개 항목)
- 기기 주소: 기본 `10.0.4.20`. 예 `192.168.1.20`.
- 액세스 PIN: Wi-Fi 접속 시 사용. 비워두면 미사용.
- 런처를 열 때 마지막 앱 다시 시작: 토글, 기본 켜짐.

### 갤러리 창
- busybar-apps 저장소의 `apps/` 목록을 표로 표시: 이름, 작성자, 설명(manifest.yaml에서).
- `설치` 버튼: 폴더 전체를 내려받아 앱 폴더에 넣고, `requirements.txt` 가 있으면 앱 전용 venv를 만들어 설치.
- 이미 설치된 앱은 `설치됨` 표시와 `삭제` 버튼.
- 진행 상황은 행 옆에 텍스트(내려받는 중 / 의존성 설치 중 / 완료 / 실패: 사유).

### 로그
- `로그 보기` 는 로그 폴더를 Finder로 연다. 앱별 `logs/<앱ID>.log` 에 stdout+stderr를 append.

## 3. 앱 발견과 실행 규약

런처가 앱으로 인정하는 폴더:

| 형태 | 판별 | 실행 명령 | cwd |
|---|---|---|---|
| 갤러리형 | `app.py` 있음 | `python app.py --host <주소> [--token <PIN>]` | 앱 폴더 |
| 저장소 패키지형 | `__init__.py` + `app.py` 있고, 부모가 `apps/` 이며 그 부모에 `pytest.ini` 가 있는 저장소 | `python -m apps.<폴더명>.app --host <주소> [--token <PIN>]` | 저장소 루트 |

- 표시 이름·설명·작성자: 같은 폴더의 `manifest.yaml` 에서 `name`, `description`, `author` 읽음. 없으면 폴더명.
  YAML은 이 세 키와 `tags:` 목록만 있는 단순 형태이므로 줄 단위 파서로 처리한다(외부 YAML 라이브러리 없음).
- 아이콘: 폴더에 `icon.png` 가 있으면 사용(정사각형 권장, 메뉴에서 16pt). 없으면 SF Symbol `app.dashed`.
- 앱 폴더 검색 위치(순서대로, 설정에서 추가 가능):
  1. `~/Library/Application Support/BUSY Launcher/apps/` (갤러리 설치 위치)
  2. 개발 모드: 저장소 `busybar/apps/`
- `--token` 은 PIN이 비어 있지 않을 때만 붙인다. 앱이 `--token` 을 모르면(argparse 오류로 즉시 종료) 한 번 더 `--token` 없이 재시도하고 로그에 남긴다.
- 환경변수 `BUSYBAR_HOST`, `BUSYBAR_TOKEN` 도 같이 넘긴다(일부 앱은 이걸 읽음).

## 4. 프로세스 관리

- `Foundation.Process` 로 실행. stdout/stderr는 파이프로 받아 로그 파일에 쓰고 마지막 200줄을 메모리에 보관.
- 상태기계: `stopped → starting → running → (exited(code) | failed(reason))`. 시작 후 2초 안에 종료되면 `failed`.
- 정지: SIGINT 전송 → 3초 대기 → 살아 있으면 SIGKILL. (우리 앱과 갤러리 앱 대부분이 SIGINT에서 화면을 지운다.)
- 앱 전환: 이전 앱 정지 완료를 기다린 뒤 새 앱 시작(화면 충돌 방지).
- 런처 종료(⌘Q, 로그아웃): 실행 중인 앱을 정지시키고, 추가로 `DELETE /api/display/draw?application_name=<앱의 application_name>` 은 알 수 없으므로 호출하지 않는다. 앱이 스스로 지운다.
- 자동 재시작 없음. 죽으면 메뉴에 `(중단됨)` 과 마지막 로그 5줄을 툴팁으로.

## 5. 기기 연결 상태

- 5초마다 `GET http://<주소>/api/version` (타임아웃 2초). 200이면 연결됨. 주소가 `10.0.4.20` 이면 "USB", 아니면 "Wi-Fi".
- PIN이 있으면 `X-API-Token` 헤더 사용.
- 상태는 메뉴 상태 줄과 아이콘(연결 안 됨이면 아이콘 흐리게)에 반영.

## 6. Python 런타임

런처는 "런타임 제공자" 하나를 통해 `python` 실행 파일 경로를 얻는다.

- **개발 모드**: 저장소의 `busybar/.venv/bin/python`. 저장소 루트는 설정 `devRepoPath` 로 지정(기본: 런처 소스에서 추론한 상위 `busybar/`).
- **번들 모드**: `.app/Contents/Resources/python/bin/python3` (python-build-standalone 3.12, aarch64-apple-darwin, install_only). 빌드 스크립트가 내려받아 넣고 `pip install busylib aiomqtt` 를 실행해 둔다.
- 선택 규칙: 번들 런타임이 존재하면 번들, 아니면 개발 모드.
- 앱별 의존성: 앱 폴더에 `requirements.txt` 가 있으면 `~/Library/Application Support/BUSY Launcher/venvs/<앱ID>/` 에 `python -m venv --system-site-packages` 로 venv를 만들고 `pip install -r requirements.txt`. 이후 그 venv의 python으로 실행. 없으면 런타임 python 직접 사용.

## 7. 저장 데이터

`~/Library/Application Support/BUSY Launcher/`
```
config.json      {"host":"10.0.4.20","token":"","resumeLastApp":true,"lastAppID":"…","extraAppsDirs":[],"devRepoPath":"…"}
apps/<appID>/    갤러리에서 받은 앱
venvs/<appID>/   앱별 의존성
logs/<appID>.log
```
앱ID = 폴더명. 갤러리 앱은 갤러리 슬러그, 저장소 앱은 패키지 폴더명.

## 8. 갤러리

- 목록: `https://api.github.com/repos/maxswinkels/busybar-apps/contents/apps` → 각 폴더의 `manifest.yaml` 을 raw URL로 읽어 이름·설명·작성자.
  목록은 1시간 캐시(`gallery-cache.json`).
- 설치: 폴더의 파일 목록을 contents API로 받아 각 파일의 `download_url` 로 내려받음(하위 폴더 재귀). 미인증 GitHub API는 시간당 60회 제한이므로 요청 수를 최소화하고, 429/403이면 "잠시 후 다시" 안내.
- 삭제: 앱 폴더와 venv, 로그 삭제. 실행 중이면 먼저 정지.

## 9. 프로젝트 구성과 빌드 (정석)

```
busybar/launcher/
├── project.yml                 # XcodeGen 스펙 → BUSY Launcher.xcodeproj 생성
├── Sources/BUSYLauncher/
│   ├── BUSYLauncherApp.swift   # @main, MenuBarExtra, LSUIElement
│   ├── Model/                  # AppDescriptor, AppRegistry(스캔), ManifestParser, Config, ProcessRunner, BarStatus, Gallery, PythonRuntime
│   ├── Views/                  # MenuView, SettingsView, GalleryView
│   └── Resources/              # Assets.xcassets(메뉴바 아이콘), Info.plist
├── Tests/BUSYLauncherTests/    # XCTest 단위 테스트
└── scripts/
    ├── bootstrap.sh            # brew install xcodegen, xcodegen generate
    ├── build.sh                # xcodebuild -scheme "BUSY Launcher" -configuration Release
    ├── bundle-python.sh        # python-build-standalone 내려받아 Resources/python에 설치 + pip
    └── package.sh              # 빌드 + 번들 + (있으면) codesign/notarize → dist/BUSY Launcher.zip
```

- 언어: Swift 6, SwiftUI, 최소 macOS 14. `LSUIElement = YES` (Dock 아이콘 없음).
- 빌드는 Xcode 27로 `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild …`. sudo 불필요.
- 서명: Developer ID 인증서가 있으면 `package.sh` 가 서명·공증. 없으면 서명 없이 zip만 만들고, README에 "우클릭 → 열기" 안내.
- 샌드박스 사용 안 함(로컬 프로세스 실행과 LAN 접속이 필요).

## 10. 에러 처리

- 기기 연결 안 됨: 앱은 그대로 시작(앱이 재시도함). 상태 줄에 표시.
- Python 런타임 없음(개발 모드에서 .venv 없음): 앱 시작 대신 알림 "저장소 .venv 가 없습니다: <경로>".
- 앱 즉시 종료(2초 내): `(중단됨)` + 로그 마지막 줄 툴팁. `--token` 인자 미지원 케이스는 §3 재시도.
- 갤러리 네트워크 오류·API 제한: 행에 사유 표시, 재시도 버튼.
- 설정의 주소가 비어 있거나 형식 오류: 저장 거부, 필드 옆 빨간 안내.
- 런처 두 개 실행: 두 번째 인스턴스는 경고 후 종료(`NSRunningApplication` 으로 확인).

## 11. 테스트

- XCTest (네트워크·프로세스 없음, `xcodebuild test`):
  - ManifestParser: 정상/키 누락/따옴표/태그 목록/빈 파일.
  - AppRegistry: 임시 디렉터리에 갤러리형·패키지형·비앱 폴더를 만들어 판별과 실행 명령(인자, cwd) 검증. `--token` 유무.
  - Config: 인코딩/디코딩, 기본값, 손상된 파일 복구.
  - ProcessRunner 상태기계: 가짜 프로세스 훅으로 starting→running→exited/failed 전환, 정지 시 SIGINT→SIGKILL 순서, 전환 시 이전 앱 정지 대기.
  - Gallery 파서: contents API JSON 샘플 → 항목, download_url 수집.
  - PythonRuntime 선택 규칙: 번들 존재/부재.
- 수동: 메뉴에서 bambu_progress 켜기/끄기/전환, 기기 연결 상태 표시, 갤러리에서 `clock` 설치 후 실행, ⌘Q 시 화면 정리, 번들 .app 을 `.venv` 없는 임시 사용자 계정 또는 폴더 이동 후 실행.

## 12. 순서

1. 개발 모드로 메뉴·실행·전환·상태·설정 완성 (Python 번들 없이).
2. 갤러리 설치.
3. Python 번들과 package.sh.
