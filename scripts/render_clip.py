cat > scripts/render_clip.py << 'PYEOF'
"""
Turns a (start, end, words) selection into a finished, downloadable,
vertical, captioned .mp4: full-bleed crop to 9:16 (no wasted blurred
padding), loudness-normalized audio, and cleaned-up animated captions
burned in via an ASS subtitle file.
"""
import os
import re
import subprocess


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Arial Black,72,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,60,60,220,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

# Contraction fragments whisper.cpp sometimes emits as their own "word"
# (e.g. "World" then "'s" as a separate token). These get merged back onto
# the previous word instead of showing as "WORLD 'S".
_CONTRACTION_FRAGMENT = re.compile(r"^'[a-zA-Z]+$")


def _ass_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def clean_words(words: list) -> list:
    """
    Cleans up raw whisper.cpp word tokens before they're shown as captions:
    - merges contraction fragments ("'s", "'re", "'t"...) onto the prior word
    - drops stray bare-dash tokens whisper sometimes emits for speaker turns
    - strips a leading dash glued onto a word (e.g. "-Loving" -> "Loving")
    """
    cleaned = []
    for w in words:
        text = w["word"].strip()
        if not text:
            continue

        if cleaned and _CONTRACTION_FRAGMENT.match(text):
            cleaned[-1]["word"] += text
            cleaned[-1]["end"] = w["end"]
            continue

        if text in ("-", "--", "—"):
            continue

        if text.startswith(("-", "—")) and len(text) > 1:
            text = text.lstrip("-—").strip()
            if not text:
                continue

        cleaned.append({"word": text, "start": w["start"], "end": w["end"]})
    return cleaned


def build_ass_captions(words: list, clip_start: float, clip_end: float, out_path: str):
    """
    Builds karaoke-style captions: groups cleaned words into short on-screen
    lines (~4-6 words) timed to when those words are actually spoken.
    """
    raw_clip_words = [w for w in words if clip_start <= w["start"] < clip_end]
    clip_words = clean_words(raw_clip_words)

    lines = []
    group = []
    GROUP_SIZE = 5
    for w in clip_words:
        group.append(w)
        if len(group) >= GROUP_SIZE:
            lines.append(group)
            group = []
    if group:
        lines.append(group)

    events = []
    for group in lines:
        start = group[0]["start"] - clip_start
        end = group[-1]["end"] - clip_start
        text = " ".join(w["word"] for w in group).upper()
        events.append(
            f"Dialogue: 0,{_ass_timestamp(max(start,0))},{_ass_timestamp(max(end,0))},Caption,,0,0,0,,{text}"
        )

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(ASS_HEADER)
        f.write("\n".join(events))


def render_clip(
    source_video: str,
    words: list,
    start_seconds: float,
    end_seconds: float,
    out_path: str,
    target_w: int = 1080,
    target_h: int = 1920,
):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    ass_path = out_path.replace(".mp4", ".ass")
    build_ass_captions(words, start_seconds, end_seconds, ass_path)

    duration = end_seconds - start_seconds

    # Full-bleed vertical crop: scale to COVER the target frame (no letterbox
    # bars, no blurred padding), then center-crop any excess width/height.
    # This fills the whole 9:16 frame with the subject, at the cost of
    # cropping off some of the sides of a widescreen source.
    vf = (
        f"trim=start={start_seconds}:end={end_seconds},setpts=PTS-STARTPTS,"
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
        f"crop={target_w}:{target_h},"
        f"ass={ass_path}"
    )
    af = f"atrim=start={start_seconds}:end={end_seconds},asetpts=PTS-STARTPTS,loudnorm"

    cmd = [
        "ffmpeg", "-y",
        "-i", source_video,
        "-vf", vf,
        "-af", af,
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "17",
        "-maxrate", "8M", "-bufsize", "16M",
        "-c:a", "aac", "-b:a", "192k",
        out_path,
    ]
    subprocess.run(cmd, check=True)
    return out_path
PYEOF