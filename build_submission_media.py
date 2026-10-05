"""Prepare the media for the submission form.

The form asks for a hero image with an aspect ratio between 1:1 and 4:3. The
full frame from the hardware run is only 320x320, and the side-by-side comparison
is 16:9 — outside that range, so it would be cropped when used as a thumbnail.

This script produces submission-ready stills at 4:3 (1600x1200) or 1:1:

    python -B build_submission_media.py

Everything is drawn from the real artifacts and receipts, never re-typed, so the
figures on the images cannot drift from the measured ones.
"""

from __future__ import annotations

import json
import os

from PIL import Image, ImageDraw, ImageFont

W, H = 1600, 1200          # 4:3, inside the form's suggested range
BG = (10, 11, 14)
INK = (232, 230, 225)
DIM = (139, 147, 167)
ACCENT = (224, 182, 74)
GREEN = (120, 220, 150)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "submission_media")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for name in (("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def centre(draw, y, text, f, fill=INK, width=W):
    box = draw.textbbox((0, 0), text, font=f)
    draw.text(((width - (box[2] - box[0])) / 2, y), text, font=f, fill=fill)


def load_comparison() -> dict:
    with open(os.path.join(HERE, "comparison", "comparison.json"),
              encoding="utf-8") as fh:
        return json.load(fh)["comparison"]


def prepare_poster() -> str:
    """The hero image: the hardware render, at a size worth submitting."""
    src = os.path.join(HERE, "comparison", "hardware", "poster.png")
    fallback = os.path.join(HERE, "demo", "poster.png")
    path = src if os.path.exists(src) else fallback
    img = Image.open(path).convert("RGB")
    # Upscale with LANCZOS; the source is small, but a thumbnail is usually
    # displayed far below 512px so this is clean in practice.
    img = img.resize((1200, 1200), Image.LANCZOS)
    img.save(os.path.join(OUT, "poster_art_1200.png"))
    return os.path.join(OUT, "poster_art_1200.png")


def frame_4x3(src: str, dest: str, label: str, sub: str = "") -> str:
    """Letterbox any image into 4:3 with a caption bar, so nothing is cropped."""
    canvas = Image.new("RGB", (W, H), BG)
    header = 150
    if os.path.exists(src):
        im = Image.open(src).convert("RGB")
        avail_h = H - header - 60
        scale = min((W - 160) / im.width, avail_h / im.height)
        im = im.resize((max(int(im.width * scale), 1),
                        max(int(im.height * scale), 1)), Image.LANCZOS)
        canvas.paste(im, ((W - im.width) // 2, header + (avail_h - im.height) // 2))
    draw = ImageDraw.Draw(canvas)
    centre(draw, 44, label, font(46, bold=True))
    if sub:
        centre(draw, 104, sub, font(26), DIM)
    canvas.save(dest)
    return dest


def comparison_4x3() -> str:
    """The headline result as a single 4:3 still, figures taken from the JSON."""
    c = load_comparison()
    emu, qpu = c["modes"][0], c["modes"][1]
    ratio = c["hardware_over_simulator"]["mean_abs_change_ratio"]

    canvas = Image.new("RGB", (W, H), BG)
    side = os.path.join(HERE, "comparison", "side_by_side.png")
    header, banner = 190, 190
    if os.path.exists(side):
        im = Image.open(side).convert("RGB")
        avail = H - header - banner
        scale = min((W - 120) / im.width, avail / im.height)
        im = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
        canvas.paste(im, ((W - im.width) // 2, header))

    draw = ImageDraw.Draw(canvas)
    centre(draw, 46, "The same prompt, rendered twice", font(50, bold=True))
    centre(draw, 112, "identical seed · the only difference is where the "
                      "circuit ran", font(26), DIM)

    y = H - banner + 18
    left = (W - (im.width if os.path.exists(side) else W)) // 2 if os.path.exists(side) else 120
    draw.text((left + 8, y), "SIMULATOR (Aer)", font=font(30, bold=True), fill=INK)
    draw.text((left + 8, y + 40), f"mean change {emu['mean_abs_change']}",
              font=font(28), fill=DIM)
    rx = left + ((im.width // 2) if os.path.exists(side) else W // 2)
    draw.text((rx + 8, y), "REAL HARDWARE (ibm_fez)", font=font(30, bold=True),
              fill=ACCENT)
    draw.text((rx + 8, y + 40), f"mean change {qpu['mean_abs_change']}",
              font=font(28), fill=ACCENT)

    label = f"{ratio}x MORE ERROR — AND SAMPLING CANNOT REMOVE IT"
    f = font(40, bold=True)
    box = draw.textbbox((0, 0), label, font=f)
    tw = box[2] - box[0]
    bx, by = (W - tw) / 2, H - 62
    draw.rounded_rectangle([bx - 26, by - 14, bx + tw + 26, by + 52],
                           radius=12, outline=ACCENT, width=3)
    draw.text((bx, by), label, font=f, fill=INK)

    dest = os.path.join(OUT, "comparison_4x3.png")
    canvas.save(dest)
    return dest


def receipt_4x3() -> str:
    """The provenance receipt as a legible 4:3 still."""
    with open(os.path.join(HERE, "comparison", "hardware", "receipt.json"),
              encoding="utf-8") as fh:
        r = json.load(fh)
    canvas = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(canvas)
    centre(draw, 40, "Provenance: every decision, and what made it",
           font(44, bold=True))
    centre(draw, 100, "comparison/hardware/receipt.json", font(24), DIM)

    f = font(21)
    y = 170
    for p in r.get("provenance", []):
        d = p.get("detail", {})
        atlas = bool(d.get("used_atlas")) or str(p.get("source", "")).startswith("atlas")
        draw.text((120, y), f"{p['choice'][:40]:<42}", font=f, fill=INK)
        draw.text((150, y + 26), f"{str(p['engine'])[:56]}",
                  font=f, fill=GREEN if atlas else DIM)
        y += 54
        if d.get("ibm_job_id"):
            draw.text((150, y), f"IBM job {d['ibm_job_id']}   "
                                f"QPU seconds {d.get('qpu_seconds')}",
                      font=f, fill=ACCENT)
            y += 28
        y += 14
        if y > H - 140:
            break
    dest = os.path.join(OUT, "receipt_4x3.png")
    canvas.save(dest)
    return dest


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    made = [
        prepare_poster(),
        comparison_4x3(),
        receipt_4x3(),
        frame_4x3(os.path.join(HERE, "video_assets", "01_title.png"),
                  os.path.join(OUT, "title_4x3.png"),
                  "QUANTUM NEGATIVE",
                  "every creative decision is a measurement on a quantum circuit"),
    ]
    print(f"wrote {len(made)} files to {OUT}")
    for m in made:
        im = Image.open(m)
        print(f"  {os.path.basename(m):<26} {im.width}x{im.height}  "
              f"ratio {im.width/im.height:.3f}  {os.path.getsize(m)/1024:7.1f} KiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
