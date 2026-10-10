# busybar-apps

Apps for the Flipper Devices **BUSY Bar** (72×16 RGB LED desk display), plus a macOS menu bar
launcher that runs them. Everything talks to the bar over its local HTTP API with
[busylib](https://github.com/busy-app/busylib-py); nothing is installed on the device.

한국어 안내는 아래에 있습니다.

| App | What it shows |
|---|---|
| `apps/bambu_progress` | Up to four Bambu Lab printers at a glance: progress bars, percentages, printing / done / paused / error, a dial-selected detail screen with remaining time, and native-style animated notices when a print finishes, pauses or fails. Reads the printers' local MQTT, no cloud. |
| `apps/media_remote` | macOS Now Playing on the bar (YouTube in Chrome, Spotify, Apple Music): artwork or thumbnail, title, elapsed time, a progress bar; OK/START toggles playback, BACK restarts or goes back, the dial seeks. Apple Music shows synced lyrics when LRCLIB has them. |
| `apps/steady_clock` | A clock whose digits sit in fixed slots, so nothing shifts when the width changes. |
| `launcher/` | **BUSY Launcher**, a native macOS menu bar app (Swift/SwiftUI) that lists the apps here and from the community gallery, runs one at a time with a bundled Python, and can disconnect the bar. |

This is a personal project and is not affiliated with Flipper Devices, BUSY, or Bambu Lab.

## Quick start (Python apps)

Python 3.12 or newer and a bar reachable over USB (default `http://10.0.4.20`) or Wi-Fi.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp apps/bambu_progress/printers.example.toml apps/bambu_progress/printers.toml
# fill in each printer's IP, serial and LAN access code (Settings > Network on the printer)

python -m apps.bambu_progress.app            # --host 192.168.1.50 for a bar on Wi-Fi
python -m apps.media_remote.app
python -m apps.steady_clock.app
```

`printers.toml` is git-ignored: your access codes never leave your machine.

No hardware yet? Run the community emulator and point the apps at it:

```bash
./scripts/setup-emulator.sh      # clones and builds tools/busybar-emulator
./scripts/run-emulator.sh        # http://127.0.0.1:8080
python -m apps.bambu_progress.app --demo --host 127.0.0.1:8080
```

## BUSY Launcher (macOS)

```bash
cd launcher
./scripts/bootstrap.sh           # Xcode command line tools + XcodeGen
./scripts/package.sh             # dist/BUSY-Launcher.zip with a bundled Python
ditto -x -k dist/BUSY-Launcher.zip /Applications
```

Open the app, set the bar's address in Settings, pick an app from the menu. The launcher has no
login item; start it yourself.

## How the display work is done

- The bar keeps every element an app has drawn, by id, and composes apps by priority. The apps
  send only the elements that changed each tick and give every element an explicit `z_index`
  (the firmware sorts by it and ties are not stable).
- Anything that has to move smoothly is a `.anim` file the bar plays itself at its own frame
  rate: the printing mark, the status pulses, the notice backdrops, the screen transitions.
  `apps/bambu_progress/anim.py` writes the container (BGR888 / BGRA8888, RLE) and the frames are
  generated at start-up from small bitmaps, so no artwork is checked in.
- Device fonts: `tiny` 4 px, `small` 5 px, `bold` 7 px, `extra_large` 10 px; only `global`
  has Hangul.

## Tests

```bash
.venv/bin/pytest -q              # Python apps
launcher/scripts/test.sh         # Swift (quit any running BUSY Launcher first)
```

## Licence and trademarks

Code is MIT (see `LICENSE`). BUSY Bar is a product of Flipper Devices; Bambu Lab, YouTube,
Spotify and Apple Music are trademarks of their owners. The printer mark drawn on the bar is a
neutral extruder by default (`[display] mark = "printer"`); a hand-drawn rendition of the Bambu
mark is available as `mark = "bambu"` for your own desk only. The `.anim` container was
implemented from the format description in the BUSY Bar firmware sources (GPLv2) and the
MIT/Apache `busybar-anim` crate; no firmware code or assets are included here.

---

## 한국어

Flipper Devices의 **BUSY Bar**(72×16 RGB LED 탁상 디스플레이)용 앱 모음과, 그 앱들을 실행하는
macOS 메뉴 막대 런처입니다. 기기에 설치하는 것이 아니라 PC에서 기기의 HTTP API로 화면을 그립니다.

- `apps/bambu_progress`: Bambu Lab 프린터 최대 4대의 진행률, 상태(출력 중·완료·일시정지·오류),
  다이얼로 고르는 상세 화면(남은 시간), 완료·일시정지·오류 알림. 프린터의 로컬 MQTT만 사용합니다.
- `apps/media_remote`: macOS에서 재생 중인 미디어(크롬 유튜브, Spotify, Apple Music)를 바에 표시하고
  버튼과 다이얼로 조작합니다. Apple Music은 가사가 있으면 함께 보여 줍니다.
- `apps/steady_clock`: 자릿수가 고정된 시계.
- `launcher/`: 앱을 골라 실행하는 macOS 메뉴 막대 앱(Swift). 파이썬을 내장해서 따로 설치할 것이 없습니다.

시작은 위 Quick start와 같습니다. `printers.toml`은 git에 올라가지 않으니 접근 코드는 안전합니다.

개인 프로젝트이며 Flipper Devices, BUSY, Bambu Lab과 관계가 없습니다. 코드는 MIT 라이선스입니다.
