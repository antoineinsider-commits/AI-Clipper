"""
Turns a (start, end, words) selection into a finished, downloadable,
vertical, captioned .mp4 -- the "every feature an expertly clipped video
will have" part: crop to 9:16, blurred-background padding if needed,
loudness-normalized audio, and animated word-by-word captions burned in
via an ASS subtitle file (karaoke-style highlight).
"""
import os
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


def _ass_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def build_ass_captions(words: list[dict], clip_start: float, clip_end: float, out_path: str):
    """
    Builds karaoke-style captions: groups words into short on-screen lines
    (~4-6 words) so captions read like modern short-form content, with each
    line timed to when those words are actually spoken.
    """
    clip_words = [w for w in words if clip_start <= w["start"] < clip_end]

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
    words: list[dict],
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

    # Crop/scale to vertical: scale so height fills target, blur-pad the
    # background, and center the sharp foreground crop on top -- avoids
    # ugly hard crops when the source is 16:9.
    vf = (
        f"[0:v]trim=start={start_seconds}:end={end_seconds},setpts=PTS-STARTPTS,"
        f"split=2[bg][fg];"
        f"[bg]scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
        f"crop={target_w}:{target_h},gblur=sigma=20[bgblur];"
        f"[fg]scale={target_w}:-2:force_original_aspect_ratio=decrease[fgscaled];"
        f"[bgblur][fgscaled]overlay=(W-w)/2:(H-h)/2,"
        f"ass={ass_path}[outv]"
    )
    af = f"atrim=start={start_seconds}:end={end_seconds},asetpts=PTS-STARTPTS,loudnorm"

    cmd = [
        "ffmpeg", "-y",
        "-i", source_video,
        "-filter_complex", vf,
        "-map", "[outv]",
        "-map", "0:a",
        "-af", af,
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        out_path,
    ]
    subprocess.run(cmd, check=True)
    return out_path
