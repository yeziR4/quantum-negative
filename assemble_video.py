"""Assemble the demo video from the built assets.

    python -B build_video_assets.py     # first: cards + 16:9 film
    python -B assemble_video.py         # then: the video itself

Output: `video_assets/quantum-negative-demo.mp4`, 1920x1080, under 3 minutes.

**No narration.** A synthetic narrator claiming authorship would sit badly beside
our written disclosure that the code was AI-built, and text cards work fine for a
judge watching muted. The score is the audio bed; if you record a voiceover, it
drops in over the top of this same cut.

Timings are deliberately conservative: the form's cap is 3 minutes and the cut
lands around 2 minutes, which leaves room to slow anything down or add a spoken
intro without re-editing.
"""

from __future__ import annotations

import json
import os
import subprocess
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
A = os.path.join(HERE, "video_assets")
OUT = os.path.join(A, "quantum-negative-demo.mp4")
W, H, FPS = 1920, 1080, 30
SR = 48000

# (asset, seconds). The film gets its own length rather than a fixed slot.
PLAN = [
    ("01_title.png", 9),
    ("film_16x9.mp4", None),      # None = use the clip's own duration
    ("02_pipeline.png", 20),
    ("03_comparison.png", 22),
    ("04_receipt.png", 18),
    ("05_repo.png", 14),
]


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{' '.join(cmd[:6])}...\n"
                           f"{result.stderr[-1500:]}")


def duration_of(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip()
    return float(out or 0)


def write_silence(path: str, seconds: float) -> str:
    """A silent stereo track, so every clip has audio and concat stays uniform."""
    n = max(int(seconds * SR), 1)
    with wave.open(path, "wb") as fh:
        fh.setnchannels(2)
        fh.setsampwidth(2)
        fh.setframerate(SR)
        fh.writeframes(np.zeros((n, 2), dtype="<i2").tobytes())
    return path


def clip_from_image(png: str, seconds: float, dest: str, silence: str) -> str:
    run(["ffmpeg", "-y", "-loglevel", "error",
         "-loop", "1", "-i", png,
         "-i", silence,
         "-c:v", "libx264", "-preset", "medium", "-crf", "19",
         "-pix_fmt", "yuv420p", "-r", str(FPS),
         "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-ac", "2",
         "-t", f"{seconds}", "-shortest", dest])
    return dest


def clip_from_video(src: str, dest: str, fade: float = 0.6) -> str:
    """Normalise the film: exact size, 48 kHz stereo, gentle fade in and out."""
    dur = duration_of(src)
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", src,
         "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x0a0b0e,"
                f"fade=t=in:st=0:d={fade},fade=t=out:st={max(dur-fade,0):.2f}:d={fade}",
         "-af", f"aresample={SR},pan=stereo|c0=c0|c1=c1,"
                f"afade=t=in:st=0:d={fade},"
                f"afade=t=out:st={max(dur-fade,0):.2f}:d={fade}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "19",
         "-pix_fmt", "yuv420p", "-r", str(FPS),
         "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-ac", "2", dest])
    return dest


def build_bed(total: float) -> str:
    """Loop our own score as the music bed, with a fade at the end."""
    score = os.path.join(HERE, "demo", "quantum_negative.wav")
    dest = os.path.join(A, "bed.m4a")
    if not os.path.exists(score):
        return ""
    run(["ffmpeg", "-y", "-loglevel", "error",
         "-stream_loop", "-1", "-i", score,
         "-t", f"{total:.2f}",
         "-af", f"aresample={SR},volume=0.35,"
                f"afade=t=in:st=0:d=2,afade=t=out:st={max(total-3,0):.2f}:d=3",
         "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", str(SR), dest])
    return dest


def main() -> int:
    os.makedirs(A, exist_ok=True)
    pieces: list[str] = []
    total = 0.0

    for name, seconds in PLAN:
        src = os.path.join(A, name)
        if not os.path.exists(src):
            print(f"  skipping missing asset: {name}")
            continue
        if seconds is None:
            dest = os.path.join(A, "_clip_" + os.path.splitext(name)[0] + ".mp4")
            clip_from_video(src, dest)
            total += duration_of(dest)
            pieces.append(dest)
            print(f"  {name:<22} {duration_of(dest):6.1f}s  (own length)")
        else:
            silence = os.path.join(A, f"_sil_{int(seconds)}.wav")
            if not os.path.exists(silence):
                write_silence(silence, seconds)
            # Derive an .mp4 name: keeping the .png extension makes ffmpeg treat
            # the output as an image sequence and refuse to write it.
            dest = os.path.join(A, "_clip_" + os.path.splitext(name)[0] + ".mp4")
            clip_from_image(src, seconds, dest, silence)
            total += seconds
            pieces.append(dest)
            print(f"  {name:<22} {seconds:6.1f}s")

    if not pieces:
        print("no assets to assemble — run build_video_assets.py first")
        return 1

    listing = os.path.join(A, "_concat.txt")
    with open(listing, "w", encoding="utf-8") as fh:
        for p in pieces:
            fh.write(f"file '{p.replace(os.sep, '/')}'\n")

    joined = os.path.join(A, "_joined.mp4")
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", listing, "-c", "copy", joined])

    bed = build_bed(total)
    if bed:
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", joined, "-i", bed,
             "-filter_complex",
             "[0:a]volume=1.0[clip];[1:a]volume=1.0[bed];"
             "[clip][bed]amix=inputs=2:duration=first:dropout_transition=0[a]",
             "-map", "0:v", "-map", "[a]",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", OUT])
    else:
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", joined,
             "-c", "copy", "-movflags", "+faststart", OUT])

    final = duration_of(OUT)
    size = os.path.getsize(OUT) / 1024 / 1024
    print()
    print(f"  video    : {OUT}")
    print(f"  duration : {final:.1f}s  ({'OK, under 3 min' if final <= 180 else 'OVER 3 MINUTES'})")
    print(f"  size     : {size:.1f} MB")
    info = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,codec_name",
         "-show_entries", "format=duration", "-of", "json", OUT],
        capture_output=True, text=True).stdout
    print(f"  probe    : {json.loads(info or '{}').get('streams')}")
    return 0 if final <= 180 else 1


if __name__ == "__main__":
    raise SystemExit(main())
