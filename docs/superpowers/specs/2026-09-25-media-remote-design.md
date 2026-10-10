# media_remote: BUSY Bar 미디어 컨트롤러 설계

- 날짜: 2026-09-25
- 위치: `apps/media_remote/` (런처 목록 이름 "Media Remote")
- 상태: 승인됨 (채팅에서 확인)

## 1. 목적

맥에서 지금 재생 중인 미디어(유튜브 in Chrome, Spotify, Apple Music 등 macOS "지금 재생 중"에 뜨는 것)를
BUSY Bar에 표시하고 기기 버튼·노브로 제어한다.

- OK/START: 재생 ↔ 일시정지
- BACK: 재생 위치가 3초를 넘으면 처음으로(0초로 이동), 3초 이내면 이전 트랙
- 노브: 한 칸 10초. 빠르게 돌리면 누적해서 한 번에 이동. 돌리는 동안 "+30s"/"-10s" 미리보기 표시
- 화면: 왼쪽에 재생 앱 아이콘(8×8), 썸네일(21×16), 제목 스크롤, 경과/전체 시간, 진행바

범위 밖: 볼륨, 셔플/반복, 플레이리스트 탐색, Safari 썸네일, Windows.

## 2. 기술 사실 (2026-09-25 이 맥, macOS 27에서 확인)

- macOS 15.4 이후 서드파티 프로세스는 MediaRemote를 직접 못 쓰지만, Apple 서명 프로세스인 `osascript`(JXA)에서
  `MediaRemote.framework`를 로드하면 된다. 커뮤니티 media-player 앱과 SKaplanOfficial gist가 같은 방식.
- 읽기: `MRNowPlayingRequest.localNowPlayingItem.nowPlayingInfo` 의 키
  `kMRMediaRemoteNowPlayingInfoTitle / Artist / Album / Duration / ElapsedTime / PlaybackRate / Timestamp`,
  `MRNowPlayingRequest.localNowPlayingPlayerPath.client.displayName / bundleIdentifier`.
  `ArtworkData`는 null(제공 안 됨). 한글 제목은 `LANG=en_US.UTF-8` 로 osascript를 실행하면 정상.
- 명령: `MRNowPlayingController.localRouteController.sendCommandOptionsCompletion(cmd, options, null)`.
  확인된 코드: 0 play, 1 pause, 2 togglePlayPause, 4 nextTrack, 5 previousTrack,
  24 seekToPlaybackPosition(옵션 `kMRMediaRemoteOptionPlaybackPosition`: 초). 17/18(skip)은 Chrome이 무시.
- 재생 중 `ElapsedTime`은 갱신되지 않는다(마지막 이벤트 시점 값). 현재 위치 = elapsed + (now − timestamp) × rate.
  `Timestamp`가 없으면 우리가 값을 받은 시각을 기준으로 한다.
- 유튜브 썸네일: MediaRemote가 아트워크를 안 주므로 Chrome AppleScript
  `tell application "Google Chrome" to get {URL, title} of every tab of every window` 로 youtube.com/watch 탭을 찾고,
  탭 제목이 "<MediaRemote 제목> - YouTube" 인 것을 골라 `v=` ID → `https://i.ytimg.com/vi/<id>/default.jpg`(120×90).
  탭이 하나뿐이면 제목 비교 없이 사용. Chrome이 안 떠 있으면 건너뜀.
- Spotify 아트워크: `tell application "Spotify" to get artwork url of current track` (Spotify가 실행 중일 때만).
- Apple Music 아트워크: 1차 범위 밖(기본 아이콘). 
- 기기: 72×16, image 요소는 업로드한 PNG를 `path`로 참조. 앱 자산은 `/ext/user_assets/media-remote/`.

## 3. 화면

```
x0-7   앱 아이콘 8×8 (세로 가운데 y4)
x9-29  썸네일 21×16 (없으면 음표 큰 아이콘 12×12 가운데)
x31-71 (41px)
  y0-6   제목, small, 흰색, 41px 넘으면 scroll_rate 20
  y8-12  "6:41/9:34" tiny 회색; 일시정지면 "‖ 6:41/9:34"
  y14-15 진행바 2px: 트랙 #2A3140, 채움 앱 색(유튜브 빨강 #FF3D3D, Spotify 초록 #1DB954, Apple Music 분홍 #FC3C44, 기타 흰색)
```
- 노브 조작 중(마지막 회전 후 0.8초 이내): y8-12 줄을 "▶ +30s" 또는 "◀ -10s" 로 바꿔 표시(앱 색).
- 재생 중인 것이 없으면: 음표 아이콘 회색 + "재생 중인 미디어 없음" tiny 회색 스크롤.
- 앱 아이콘(8×8 비트맵, 코드 내): youtube(빨간 둥근 사각 + 흰 삼각), spotify(초록 원 + 3개 호), music(분홍 음표),
  generic(흰 음표). 판별: bundle `com.google.Chrome`/`com.apple.Safari`/… + 유튜브 탭 매칭 → youtube;
  `com.spotify.client` → spotify; `com.apple.Music` → music; 그 외 generic.
- 갱신 주기: 상태 폴링 1초, 화면 그리기 0.5초(진행바·시간이 부드럽게), 노브 미리보기는 즉시.

## 4. 구성요소 (`apps/media_remote/`)

| 모듈 | 책임 |
|---|---|
| `nowplaying.py` | JXA 스크립트 문자열, `run_jxa(mode, arg)`(osascript 호출, UTF-8), `parse_info(json)->NowPlaying`, `position(np, now)`, `send(cmd, position=None)` |
| `thumbs.py` | `chrome_tabs()`(AppleScript), `youtube_id_for(title, tabs)`, `fetch_youtube_thumb(id)`, `spotify_artwork_url()`, `to_thumb_png(bytes, 21×16)`(Pillow, 4:3 → 가운데 크롭 후 축소), 디스크 캐시 `~/Library/Caches/busybar-media-remote/` |
| `icons.py` | 앱 아이콘 비트맵·색, PNG 인코딩(bambu_progress의 to_png 재사용: 같은 저장소 패키지 import) |
| `render.py` | `render(np, thumb_path, seek_preview, frame)->DisplayElements`, `render_idle()` |
| `controller.py` | `SeekAccumulator`(delta 누적, 0.8초 정지 후 확정, 미리보기 텍스트), `back_action(np)->"restart"|"previous"`, `Ui` 상태 |
| `app.py` | CLI(`--host`, `--token`, `--once`, `--print-only`), 폴링 루프, 입력 루프(bambu_progress와 같은 parse_input_events), Painter와 같은 그리기(요소 id 고정이라 clear_before_draw 불필요, 트랙 바뀌면 전체 clear) |
| `requirements.txt` | `pillow` |
| `manifest.yaml`, `icon.png` | 런처/갤러리용 |

`NowPlaying`: `active, app_name, bundle_id, title, artist, duration, elapsed, rate, timestamp(우리 수신 시각), kind(youtube|spotify|music|generic), media_key(썸네일 캐시 키: 유튜브 ID 또는 title+artist)`.

입력 처리:
- 버튼 ok/start(press) → `send(2)`; 낙관적으로 rate를 0↔1로 바꿔 즉시 화면 반영, 다음 폴링에서 실제 값으로.
- back(press) → `position > 3` 이면 `send(24, 0)` 아니면 `send(5)`.
- encoder delta → `SeekAccumulator.add(delta*10)`; 0.8초 뒤 확정 시 `target = clamp(position + total, 0, duration)` 로 `send(24, target)`; 화면은 즉시 target 기준으로 표시.

## 5. 에러 처리

- osascript 실패/타임아웃(3초): 이전 상태 유지, 3회 연속 실패 시 화면에 "MediaRemote 오류" tiny + 로그.
- Chrome 미실행/AppleScript 거부: 썸네일 없이 진행. 자동화 권한 프롬프트가 뜰 수 있음(README에 안내).
- 썸네일 다운로드 실패: 캐시 없으면 기본 아이콘, 재시도는 트랙 바뀔 때.
- 이동 대상 앱이 seek를 무시: 다음 폴링에서 실제 위치로 되돌아감(사용자에겐 "안 움직임"으로 보임). 로그에 남김.
- 기기 409/연결 끊김: bambu_progress와 동일(무시 후 재시도, 시작 시 대기).

## 6. 테스트

- 단위(pytest, 네트워크·osascript 없음): `parse_info`(정상/비활성/한글/누락), `position`(재생·정지·timestamp 없음),
  `youtube_id_for`(단일 탭/제목 매칭/없음/재생목록 URL), `to_thumb_png`(크기·크롭), `SeekAccumulator`(누적·확정·미리보기 문자열),
  `back_action`, `render`(요소 위치·색·스크롤·미리보기 줄·idle), 앱 아이콘 판별.
- 수동: 유튜브 재생 중 실기기에서 OK/BACK/노브 확인, Spotify로 같은 확인, 아무것도 없을 때 idle 화면.
