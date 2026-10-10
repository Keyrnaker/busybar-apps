<p align="right">
  <a href="README.md"><img alt="English" src="https://img.shields.io/badge/English-2A3140?style=for-the-badge"></a>
  <a href="README.ko.md"><img alt="한국어" src="https://img.shields.io/badge/한국어-3DDC84?style=for-the-badge"></a>
</p>

<p align="center">
  <img src="docs/images/grid.png" width="576" alt="BUSY Bar에 표시된 Bambu Lab 프린터 네 대">
</p>

<h1 align="center">busybar-apps</h1>

<p align="center">
  Flipper <b>BUSY Bar</b>의 72×16 LED 화면을 제대로 써먹는 앱들과,<br>
  그 앱들을 실행하는 macOS 메뉴 막대 런처.
</p>

<p align="center">
  <a href="LICENSE"><img alt="MIT" src="https://img.shields.io/badge/license-MIT-3DDC84"></a>
  <img alt="Python 3.12" src="https://img.shields.io/badge/python-3.12-3776AB">
  <img alt="macOS 14+" src="https://img.shields.io/badge/launcher-macOS%2014%2B-000000">
  <img alt="tests" src="https://img.shields.io/badge/tests-163%20passing-3DDC84">
</p>

---

## 구성

| | |
|---|---|
| **`bambu_progress`** | Bambu Lab 프린터 상태를 실시간으로. 한 화면에 네 대, 다이얼로 고르고 OK로 상세 화면. 완료·일시정지·오류 알림은 바의 기본 화면과 같은 시각 언어로. 프린터의 로컬 MQTT만 쓰고 클라우드나 개발자 모드는 필요 없습니다. |
| **`media_remote`** | macOS에서 재생 중인 미디어(크롬 유튜브, Spotify, Apple Music)를 바에. 앨범 아트나 썸네일, 제목, 시간, 진행바. OK/START로 재생·일시정지, BACK으로 처음부터 또는 이전 곡, 다이얼로 탐색. Apple Music은 싱크 가사까지. |
| **`steady_clock`** | 자릿수마다 자리가 고정되어 흔들리지 않는 시계. |
| **`launcher/`** | **BUSY Launcher**, Swift로 만든 메뉴 막대 앱. 이 저장소의 앱과 커뮤니티 갤러리의 앱을 골라 하나씩 실행하고, 파이썬을 내장하며, 바 연결과 해제를 담당합니다. zip을 설치하면 터미널은 잊어도 됩니다. |

## bambu_progress 자세히

<p align="center">
  <img src="docs/images/grid-selected.png" width="576" alt="다이얼 선택"><br>
  <sub>다이얼을 돌리면 테두리가 프린터를 고릅니다. 10초 뒤 저절로 사라집니다.</sub>
</p>

<p align="center">
  <img src="docs/images/detail.png" width="576" alt="상세 화면"><br>
  <sub>OK를 누르면 물결 효과 뒤 상세 화면. 왼쪽에 큰 마크와 이름, 오른쪽에 퍼센트와 남은 시간.</sub>
</p>

<p align="center">
  <img src="docs/images/notice-done.png" width="576" alt="완료 알림"><br>
  <sub>출력이 끝나면 흐르는 배경 위에 체크가 그려지고, 이어서 프린터 이름이 나옵니다. 일시정지와 오류는 호박색과 빨강으로 같은 방식.</sub>
</p>

움직이는 것은 전부 바가 자체 프레임 속도로 재생하는 `.anim` 파일입니다. 마크를 타고 내려오는
필라멘트 점, 오류 숨쉬기, 알림 배경, 진입 물결까지. 프레임은 7×8 비트맵 몇 개에서 시작할 때
생성되므로 관리할 그림 파일이 없고, HTTP로 다시 그리느라 끊기는 일도 없습니다.

## 빠른 시작

Python 3.12 이상과 USB(`http://10.0.4.20`로 응답) 또는 Wi-Fi로 연결된 바가 필요합니다.

```bash
git clone https://github.com/Keyrnaker/busybar-apps.git && cd busybar-apps
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp apps/bambu_progress/printers.example.toml apps/bambu_progress/printers.toml
# 프린터마다 IP, 시리얼, LAN 접근 코드를 채웁니다 (프린터 설정 › 네트워크)

python -m apps.bambu_progress.app             # Wi-Fi 바는 --host 192.168.1.50 처럼 지정
python -m apps.media_remote.app
python -m apps.steady_clock.app
```

`printers.toml`은 git에 올라가지 않으므로 접근 코드는 내 컴퓨터에만 남습니다.

<details>
<summary>아직 바가 없다면 에뮬레이터로.</summary>

```bash
./scripts/setup-emulator.sh       # tools/busybar-emulator 클론과 빌드
./scripts/run-emulator.sh         # http://127.0.0.1:8080
python -m apps.bambu_progress.app --demo --host 127.0.0.1:8080
```
</details>

<details>
<summary>설정 (<code>printers.toml</code>)</summary>

```toml
[busybar]
host = "10.0.4.20"      # USB 기본값; --host가 우선
token = ""              # Wi-Fi 접근 PIN을 설정했다면

[[printers]]
name = "H2S"            # 상세 화면 4글자, 그리드 3글자까지
ip = "192.168.0.31"
serial = "0938BJ000000000"
access_code = "12345678"

[display]
layout = "grid"         # grid: 한 화면에 네 대 | list: 두 대, 긴 이름
mark = "bambu"          # bambu: 직접 그린 뱀부 마크 | printer: 중립적인 익스트루더 모양
```
</details>

## BUSY Launcher (macOS)

```bash
cd launcher
./scripts/bootstrap.sh            # Xcode 명령줄 도구 + XcodeGen
./scripts/package.sh              # 파이썬이 내장된 dist/BUSY-Launcher.zip
ditto -x -k dist/BUSY-Launcher.zip /Applications
```

앱을 열고 설정에서 바 주소를 넣은 뒤 메뉴에서 앱을 고르면 됩니다. 로그인 시 자동 실행은 일부러
넣지 않았습니다. 필요할 때 켜세요.

## 바 앱을 직접 만드는 분을 위한 메모

펌웨어 1.2.4에서 알아내는 데 시간이 걸렸던 것들입니다.

- **모든 요소에 `z_index`를 주세요.** 바는 요소를 z_index로 정렬하는데 불안정 정렬이고, 값이 없는
  요소는 요청 안의 순서대로 `0, 10, 20…`을 받습니다. 요청이 다르면 값이 겹쳐서 갱신 때마다
  위아래가 뒤바뀝니다.
- **바뀐 요소만 보내세요.** 요소는 id로 유지되며, 애니메이션을 다시 보내면 첫 프레임부터 다시 시작합니다.
- **id의 종류는 바꿀 수 없습니다.** 같은 id로 이미지를 애니메이션으로 바꾸면 거부됩니다. 다른 id를 쓰세요.
- **1.2.4의 `.anim`은 `bicycle0` 컨테이너입니다.** 펌웨어 저장소의 `seq2anim.py`는 `bicycle1`을
  쓰는데, 이 펌웨어는 그걸 자리표시 그림으로 보여 줍니다. `apps/bambu_progress/anim.py`가 펌웨어
  RLE로 BGR888/BGRA8888 프레임을 씁니다. 알파가 동작해서 마스크와 오버레이가 쉽습니다.
- **글꼴**: `tiny` 4px, `small` 5px, `bold` 7px, `extra_large` 10px. 한글은 `global`에만 있습니다.
- **`stock_path`로 쓸 수 있는 내장 자원**은 `shared/` 아래 것뿐입니다. 바 자체의 상태·전환
  애니메이션은 불러올 수 없습니다.

## 테스트

```bash
.venv/bin/pytest -q               # 파이썬 앱
launcher/scripts/test.sh          # Swift; 실행 중인 BUSY Launcher를 먼저 종료
```

## 라이선스와 상표

코드는 MIT입니다. 개인 프로젝트이며 Flipper Devices, BUSY, Bambu Lab, Google, Spotify, Apple과
관계가 없습니다. BUSY Bar, Bambu Lab, YouTube, Spotify, Apple Music은 각 소유자의 상표입니다.
픽셀로 그린 뱀부 마크는 바에서 뱀부 프린터를 가리키는 용도일 뿐이며, 중립적인 모양을 원하면
`mark = "printer"`로 바꾸면 됩니다. 펌웨어 코드나 에셋은 포함하지 않았고, `.anim` 컨테이너는
GPLv2 펌웨어 소스의 포맷 설명과 MIT/Apache `busybar-anim` 크레이트를 보고 구현했습니다.
