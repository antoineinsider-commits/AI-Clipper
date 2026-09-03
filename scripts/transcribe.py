"""
Runs whisper.cpp on the extracted audio and returns a word-level transcript:
a list of {"word": str, "start": float, "end": float}.

Fully local -- whisper.cpp binary + ggml model, no network calls.
"""
import json
import os
import subprocess


def extract_audio(video_path: str, out_wav: str = "work/audio.wav") -> str:
    os.makedirs(os.path.dirname(out_wav), exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
        out_wav,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_wav


def transcribe(video_path: str) -> list[dict]:
    whisper_bin = os.environ.get("WHISPER_BIN", "whisper.cpp/build/bin/whisper-cli")
    model_path = os.environ.get("WHISPER_MODEL_PATH", "whisper.cpp/models/ggml-base.en.bin")

    wav_path = extract_audio(video_path)
    out_prefix = "work/transcript"

    cmd = [
        whisper_bin,
        "-m", model_path,
        "-f", wav_path,
        "-ml", "1",          # force near word-level segments
        "-oj",                # output JSON
        "-of", out_prefix,
        "-nt",                # no timestamps printed to stdout (we read the JSON)
    ]
    subprocess.run(cmd, check=True)

    with open(f"{out_prefix}.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    words = []
    for seg in data.get("transcription", []):
        text = seg.get("text", "").strip()
        if not text:
            continue
        offsets = seg.get("offsets", {})
        start = offsets.get("from", 0) / 1000.0
        end = offsets.get("to", 0) / 1000.0
        words.append({"word": text, "start": start, "end": end})

    if not words:
        raise RuntimeError("Transcription produced no words -- check audio/model.")

    return words


def words_to_plaintext_with_timestamps(words: list[dict], interval_sec: float = 10.0) -> str:
    """
    Collapses word-level output into a compact timestamped transcript, e.g.

    [00:00] Hey everyone welcome back to the channel today we're going to
    [00:10] talk about something that changed everything for me...

    This is what gets fed to the LLM -- compact but time-anchored, so the
    model can propose accurate clip start/end times.
    """
    lines = []
    current_line = []
    next_marker = 0.0
    for w in words:
        if w["start"] >= next_marker:
            if current_line:
                lines.append(" ".join(current_line))
                current_line = []
            minutes = int(w["start"] // 60)
            seconds = int(w["start"] % 60)
            current_line.append(f"[{minutes:02d}:{seconds:02d}]")
            next_marker += interval_sec
        current_line.append(w["word"])
    if current_line:
        lines.append(" ".join(current_line))
    return "\n".join(lines)
