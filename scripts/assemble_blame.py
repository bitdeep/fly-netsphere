#!/usr/bin/env python3
"""Ken Burns short: a fruit fly lost in a BLAME!-inspired City."""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
BLAME = ROOT / "out/blame"
OUT = ROOT / "out"
SHOTS = OUT / "blame_shots"
W, H, FPS = 1280, 720, 30


def font(size: int) -> ImageFont.FreeTypeFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def title_card(path: Path, lines: list[tuple[str, int]], subtitle: str | None = None):
    img = Image.new("RGB", (W, H), (5, 5, 7))
    draw = ImageDraw.Draw(img)
    # thin frame, Nihei panel
    draw.rectangle((24, 24, W - 25, H - 25), outline=(70, 70, 74), width=1)
    total_h = sum(sz + 12 for _, sz in lines)
    y = (H - total_h) // 2 - 10
    for text, sz in lines:
        f = font(sz)
        bbox = draw.textbbox((0, 0), text, font=f)
        tw = bbox[2] - bbox[0]
        draw.text(((W - tw) // 2, y), text, font=f, fill=(230, 230, 226))
        y += sz + 12
    if subtitle:
        f = font(22)
        bbox = draw.textbbox((0, 0), subtitle, font=f)
        tw = bbox[2] - bbox[0]
        draw.text(((W - tw) // 2, H - 80), subtitle, font=f, fill=(140, 140, 138))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


def still_to_video(image: Path, dest: Path, seconds: float, zoom_end: float = 1.18):
    frames = int(seconds * FPS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # zoompan d is output frames; s is output size
    z_inc = (zoom_end - 1.0) / max(frames - 1, 1)
    vf = (
        f"scale=8000:-1,"
        f"zoompan=z='1+{z_inc}*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={frames}:s={W}x{H}:fps={FPS},"
        f"eq=contrast=1.12:brightness=-0.04:gamma=0.92,"
        f"format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-i", str(image),
        "-vf", vf,
        "-t", f"{seconds:.2f}",
        "-r", str(FPS),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
        str(dest),
    ]
    subprocess.check_call(cmd)


def card_to_video(image: Path, dest: Path, seconds: float):
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-i", str(image),
        "-t", f"{seconds:.2f}",
        "-r", str(FPS),
        "-vf", f"scale={W}:{H},format=yuv420p",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
        str(dest),
    ]
    subprocess.check_call(cmd)


def concat(paths: list[Path], dest: Path):
    lst = dest.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in paths))
    subprocess.check_call(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(lst),
            "-c", "copy",
            str(dest),
        ]
    )


def maybe_grade_sim(src: Path, dest: Path, seconds: float | None = None):
    if not src.exists():
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    vf = (
        "hue=s=0,eq=contrast=1.25:brightness=-0.06:gamma=0.9,"
        f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src),
        "-vf", vf,
        "-r", str(FPS),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
    ]
    if seconds:
        cmd.extend(["-t", f"{seconds:.2f}"])
    cmd.append(str(dest))
    subprocess.check_call(cmd)
    return dest


def main():
    SHOTS.mkdir(parents=True, exist_ok=True)
    cards = []
    cards.append(
        title_card(
            SHOTS / "t0.png",
            [("LEVEL UNKNOWN", 64)],
            "The City has no top and no bottom",
        )
    )
    cards.append(
        title_card(
            SHOTS / "t1.png",
            [("Net Terminal Gene", 40), ("not found", 40)],
        )
    )
    cards.append(
        title_card(
            SHOTS / "t2.png",
            [("Safeguard: ignored", 36), ("too small", 28)],
        )
    )
    cards.append(
        title_card(
            SHOTS / "t3.png",
            [("a Drosophila", 36), ("in The City", 36)],
            "fan homage to BLAME!  ·  flybody / DeepMind + Janelia",
        )
    )

    seq: list[Path] = []
    card_to_video(SHOTS / "t0.png", SHOTS / "s00.mp4", 2.8)
    seq.append(SHOTS / "s00.mp4")

    still_to_video(BLAME / "corridor.jpg", SHOTS / "s01.mp4", 5.5, 1.22)
    seq.append(SHOTS / "s01.mp4")

    card_to_video(SHOTS / "t1.png", SHOTS / "s02.mp4", 2.4)
    seq.append(SHOTS / "s02.mp4")

    still_to_video(BLAME / "corridor_fly.jpg", SHOTS / "s03.mp4", 5.0, 1.22)
    seq.append(SHOTS / "s03.mp4")

    hero = BLAME / "flybody_in_city.jpg"
    if hero.exists():
        still_to_video(hero, SHOTS / "s03b.mp4", 6.5, 1.32)
        seq.append(SHOTS / "s03b.mp4")

    nihei = BLAME / "fly_nihei.jpg"
    if nihei.exists():
        still_to_video(nihei, SHOTS / "s04.mp4", 5.2, 1.10)
        seq.append(SHOTS / "s04.mp4")
    else:
        still_to_video(BLAME / "fly_closeup.jpg", SHOTS / "s04.mp4", 5.0, 1.12)
        seq.append(SHOTS / "s04.mp4")

    still_to_video(BLAME / "shaft_fly.jpg", SHOTS / "s05.mp4", 5.5, 1.25)
    seq.append(SHOTS / "s05.mp4")

    still_to_video(BLAME / "hall.jpg", SHOTS / "s06.mp4", 4.5, 1.14)
    seq.append(SHOTS / "s06.mp4")

    card_to_video(SHOTS / "t2.png", SHOTS / "s08.mp4", 3.0)
    seq.append(SHOTS / "s08.mp4")
    card_to_video(SHOTS / "t3.png", SHOTS / "s09.mp4", 3.2)
    seq.append(SHOTS / "s09.mp4")

    dest = OUT / "drosophila_level_unknown.mp4"
    concat(seq, dest)
    print(f"wrote {dest} ({dest.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
