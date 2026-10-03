"""Build the graphic assets for the demo video.

Produces 1920x1080 PNG cards plus a 16:9 version of the film, all deterministic
so the video can be rebuilt from scratch with one command.

    python -B build_video_assets.py

Cards are drawn with PIL and only the fonts that ship with Pillow, so this runs
anywhere without downloading a typeface.
"""

from __future__ import annotations

import json
import os
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
BG = (10, 11, 14)
INK = (232, 230, 225)
DIM = (139, 147, 167)
ACCENT = (224, 182, 74)
GREEN = (120, 220, 150)
RED = (224, 119, 119)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "video_assets")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """A font that ships with Pillow, so no download is needed."""
    for name in (("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
                 ("DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf")):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def mono(size: int) -> ImageFont.FreeTypeFont:
    for name in ("DejaVuSansMono.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def blank() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG)
    return img, ImageDraw.Draw(img)


def centre(draw: ImageDraw.ImageDraw, y: int, text: str,
           f: ImageFont.FreeTypeFont, fill=INK) -> None:
    box = draw.textbbox((0, 0), text, font=f)
    draw.text(((W - (box[2] - box[0])) / 2, y), text, font=f, fill=fill)


def tracked(draw: ImageDraw.ImageDraw, y: int, text: str,
            f: ImageFont.FreeTypeFont, fill=INK, gap: int = 6) -> None:
    """Letter-spaced text, for the title treatment."""
    widths = [draw.textbbox((0, 0), ch, font=f)[2] for ch in text]
    total = sum(widths) + gap * (len(text) - 1)
    x = (W - total) / 2
    for ch, w in zip(text, widths):
        draw.text((x, y), ch, font=f, fill=fill)
        x += w + gap


def card_title() -> str:
    img, draw = blank()
    # A faint copy of the poster as the backdrop.
    poster = os.path.join(HERE, "demo", "poster.png")
    if os.path.exists(poster):
        bg = Image.open(poster).convert("RGB").resize((H, H), Image.BICUBIC)
        bg = bg.filter(__import__("PIL.ImageFilter", fromlist=["ImageFilter"])
                       .GaussianBlur(40))
        canvas = Image.new("RGB", (W, H), BG)
        canvas.paste(bg, ((W - H) // 2, 0))
        img = Image.blend(canvas, Image.new("RGB", (W, H), BG), 0.55)
        draw = ImageDraw.Draw(img)

    tracked(draw, 430, "QUANTUM NEGATIVE", font(96, bold=True), INK, gap=10)
    centre(draw, 560, "every creative decision is a measurement", font(40), DIM)
    centre(draw, 620, "on a quantum circuit", font(40), DIM)
    centre(draw, 760, "Moth Hack 2026  ·  Advanced 2: Quantum-native #2",
           font(30), ACCENT)
    path = os.path.join(OUT, "01_title.png")
    img.save(path)
    return path


def card_pipeline() -> str:
    img, draw = blank()
    centre(draw, 150, "How one frame is decided", font(54, bold=True), INK)

    steps = [
        ("prompt", "text"),
        ("sha256 -> seed", "deterministic"),
        ("256 values", "derived array"),
        ("qpixl-v1 on ibm_fez", "encode / measure / decode"),
        ("measurement", "what came back"),
        ("melody · colour · structure", "the artwork"),
    ]
    top, box_h, gap = 300, 96, 26
    for i, (label, sub) in enumerate(steps):
        y = top + i * (box_h + gap)
        accent = ACCENT if "ibm_fez" in label else (60, 66, 82)
        draw.rounded_rectangle([360, y, W - 360, y + box_h], radius=14,
                               outline=accent, width=3 if "ibm_fez" in label else 2)
        draw.text((400, y + (12 if sub else 26)), label, font=font(38, bold=True),
                  fill=INK if "ibm_fez" in label else INK)
        if sub:
            draw.text((400, y + 56), sub, font=font(24), fill=DIM)
    centre(draw, top + len(steps) * (box_h + gap) + 20,
           "hardware noise is part of the material, not removed from it",
           font(28), DIM)
    path = os.path.join(OUT, "02_pipeline.png")
    img.save(path)
    return path


def card_comparison() -> str:
    """The measured numbers, big, over the side-by-side image."""
    src = os.path.join(HERE, "comparison", "side_by_side.png")
    img = Image.new("RGB", (W, H), BG)
    side = None
    if os.path.exists(src):
        side = Image.open(src).convert("RGB")
        # Room above for the headline, below for the figures.
        scale = min((W - 300) / side.width, (H - 570) / side.height)
        side = side.resize((int(side.width * scale), int(side.height * scale)),
                           Image.BICUBIC)
        img.paste(side, ((W - side.width) // 2, 250))
    draw = ImageDraw.Draw(img)

    centre(draw, 56, "The same prompt, rendered twice", font(54, bold=True), INK)
    centre(draw, 130, "identical seed · the only difference is where the "
                      "circuit ran", font(28), DIM)

    with open(os.path.join(HERE, "comparison", "comparison.json"),
              encoding="utf-8") as fh:
        payload = json.load(fh)["comparison"]
    emu, qpu = payload["modes"][0], payload["modes"][1]
    ratio = payload["hardware_over_simulator"]["mean_abs_change_ratio"]

    # Figures sit directly beneath the image each one describes.
    y = 250 + (side.height if side else 400) + 30
    left_x = (W - (side.width if side else W)) // 2 if side else 300
    right_x = left_x + ((side.width // 2) if side else W // 2)
    draw.text((left_x + 8, y), "SIMULATOR (Aer)",
              font=font(32, bold=True), fill=INK)
    draw.text((left_x + 8, y + 44), f"mean change {emu['mean_abs_change']}",
              font=font(30), fill=DIM)
    draw.text((right_x + 8, y), "REAL HARDWARE (ibm_fez)",
              font=font(32, bold=True), fill=ACCENT)
    draw.text((right_x + 8, y + 44), f"mean change {qpu['mean_abs_change']}",
              font=font(30), fill=ACCENT)

    # The headline number, given the visual weight it deserves.
    banner = f"{ratio}x MORE ERROR — AND SAMPLING CANNOT REMOVE IT"
    f = font(50, bold=True)
    box = draw.textbbox((0, 0), banner, font=f)
    tw, th = box[2] - box[0], box[3] - box[1]
    bx, by = (W - tw) / 2, H - 128
    draw.rounded_rectangle([bx - 34, by - 20, bx + tw + 34, by + th + 28],
                           radius=14, outline=ACCENT, width=3)
    draw.text((bx, by), banner, font=f, fill=INK)
    path = os.path.join(OUT, "03_comparison.png")
    img.save(path)
    return path


def card_receipt() -> str:
    """The provenance receipt, rendered as a terminal-like panel."""
    with open(os.path.join(HERE, "comparison", "hardware", "receipt.json"),
              encoding="utf-8") as fh:
        r = json.load(fh)
    img, draw = blank()
    centre(draw, 60, "Provenance: every decision, and what made it",
           font(48, bold=True), INK)
    centre(draw, 130, "comparison/hardware/receipt.json", font(26), DIM)

    f = mono(23)
    y = 210
    draw.rounded_rectangle([140, y - 16, W - 140, H - 90], radius=12,
                           fill=(16, 18, 23), outline=(40, 45, 56), width=2)
    y += 20
    for p in r.get("provenance", []):
        d = p.get("detail", {})
        atlas = bool(d.get("used_atlas")) or str(p.get("source", "")).startswith("atlas")
        colour = GREEN if atlas else DIM
        draw.text((180, y), f"{p['choice'][:38]:<40}", font=f, fill=INK)
        y += 28
        draw.text((210, y), f"{str(p['engine'])[:52]:<54} {p.get('source','')}",
                  font=f, fill=colour)
        y += 28
        if d.get("ibm_job_id"):
            draw.text((210, y), f"IBM job {d['ibm_job_id']}   "
                                f"QPU seconds {d.get('qpu_seconds')}",
                      font=f, fill=ACCENT)
            y += 28
        if d.get("params_clamped"):
            draw.text((210, y), f"params clamped: {d['params_clamped']}",
                      font=f, fill=DIM)
            y += 28
        y += 10
        if y > H - 150:
            break
    path = os.path.join(OUT, "04_receipt.png")
    img.save(path)
    return path


def card_repo() -> str:
    img, draw = blank()
    tracked(draw, 300, "EVERYTHING IS PUBLIC", font(64, bold=True), INK, gap=8)
    centre(draw, 430, "github.com/yeziR4/quantum-negative", font(44), ACCENT)
    centre(draw, 540, "the pipeline · the notebook · both receipts",
           font(30), DIM)
    centre(draw, 590, "the simulator-vs-hardware comparison", font(30), DIM)
    centre(draw, 700, "269 automated checks, all passing", font(34, bold=True), INK)
    centre(draw, 770, "six suites: physics, pipeline, notebook, web app, game, "
                      "Atlas API", font(26), DIM)
    centre(draw, 880, "Run on IBM quantum hardware via Moth Atlas",
           font(28), GREEN)
    path = os.path.join(OUT, "05_repo.png")
    img.save(path)
    return path


def film_16x9() -> str:
    """The film, letterboxed into 16:9 with a subtle border.

    The source is square, so it is scaled to full height and centred rather than
    cropped, which would cut the composition.
    """
    src = os.path.join(HERE, "demo", "quantum_negative.mp4")
    dest = os.path.join(OUT, "film_16x9.mp4")
    if not os.path.exists(src):
        return ""
    vf = (f"scale=-2:{H}:flags=bicubic,"
          f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x0a0b0e,"
          f"drawbox=x=0:y=0:w={W}:h={H}:color=0x1a1d24@1:t=4")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-vf", vf,
           "-c:v", "libx264", "-preset", "medium", "-crf", "20",
           "-pix_fmt", "yuv420p", "-an", dest]
    subprocess.run(cmd, check=True)
    return dest


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    made = [card_title(), card_pipeline(), card_comparison(), card_receipt(),
            card_repo()]
    film = film_16x9()
    if film:
        made.append(film)
    print(f"wrote {len(made)} assets to {OUT}")
    for m in made:
        size = os.path.getsize(m)
        print(f"  {os.path.basename(m):<22} {size/1024:8.1f} KiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
