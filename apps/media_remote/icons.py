"""Source-app icons (8x8) and the no-thumbnail placeholder, encoded with the bambu app's PNG writer."""
from __future__ import annotations

from apps.bambu_progress.icons import DIM, WHITE, to_png

from .nowplaying import NowPlaying

KIND_COLORS = {"youtube": "#FF3D3D", "spotify": "#1DB954", "music": "#FC3C44", "generic": "#FFFFFF"}
PLACEHOLDER = "note_big.png"

# '#' = kind colour, 'o' = white accent, '.' = transparent
BITMAPS: dict[str, tuple[str, ...]] = {
    "youtube": (   # video: a screen with a play triangle (no brand mark)
        "########",
        "#......#",
        "#.o....#",
        "#.oo...#",
        "#.ooo..#",
        "#.oo...#",
        "#.o....#",
        "########",
    ),
    "spotify": (   # streaming audio: equaliser bars (no brand mark)
        "........",
        "......#.",
        "..#...#.",
        "..#.#.#.",
        "#.#.#.#.",
        "#.#.#.#.",
        "#.#.#.#.",
        "........",
    ),
    "music": (     # note
        ".....##.",
        "....####",
        "....#.##",
        "....#...",
        "....#...",
        "..###...",
        ".####...",
        "..##....",
    ),
    "generic": (   # note
        ".....##.",
        "....####",
        "....#.##",
        "....#...",
        "....#...",
        "..###...",
        ".####...",
        "..##....",
    ),
    "note_big": (  # 12x12 placeholder when there is no thumbnail
        "........####",
        "........####",
        ".......##..#",
        ".......#....",
        ".......#....",
        ".......#....",
        ".......#....",
        "....####....",
        "...#####....",
        "...#####....",
        "....###.....",
        "............",
    ),
}


def kind_for(np: NowPlaying, has_youtube_tab: bool) -> str:
    if not np.active:
        return "generic"
    if np.bundle_id == "com.spotify.client":
        return "spotify"
    if np.bundle_id == "com.apple.Music":
        return "music"
    if has_youtube_tab:
        return "youtube"
    return "generic"


def icon_filename(kind: str, dim: bool = False) -> str:
    return f"app_{kind}_dim.png" if dim else f"app_{kind}.png"


def required_icons() -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for kind, color in KIND_COLORS.items():
        out[icon_filename(kind)] = to_png(BITMAPS[kind], {"#": color, "o": WHITE})
        out[icon_filename(kind, dim=True)] = to_png(BITMAPS[kind], {"#": DIM, "o": DIM})
    out[PLACEHOLDER] = to_png(BITMAPS["note_big"], {"#": DIM})
    return out
