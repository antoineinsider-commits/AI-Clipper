"""
Entry point: fetch -> transcribe -> select moments -> render clips -> inspect
-> write report. Designed to be run by the GitHub Actions workflow, reading
config from environment variables.
"""
import json
import os
import time

import fetch
import transcribe as transcribe_mod
import select_moments as select_mod
import render_clip as render_mod
import inspector as inspector_mod

TIME_BUDGET_SECONDS = 9 * 60  # aim to land inside the 5-10 min promise
LONG_VIDEO_THRESHOLD_SECONDS = 45 * 60


def get_video_duration(path: str) -> float:
    import subprocess
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def sample_transcript_if_long(words: list[dict], video_duration: float, transcript_text: str) -> str:
    """
    For long videos, keep transcription (cheap) but reduce what we feed the
    LLM so we stay inside the time budget: chunk into 2-minute windows,
    score by speech density + simple excitement keywords, and keep only the
    top ~40% of windows plus their neighbors for context.
    """
    if video_duration <= LONG_VIDEO_THRESHOLD_SECONDS:
        return transcript_text

    EXCITEMENT_WORDS = {
        "amazing", "insane", "crazy", "unbelievable", "wow", "no way",
        "what", "why", "how", "never", "worst", "best", "secret", "wait",
        "actually", "literally", "shocked", "can't believe",
    }
    window = 120.0
    windows = {}
    for w in words:
        idx = int(w["start"] // window)
        windows.setdefault(idx, []).append(w)

    scored = []
    for idx, ws in windows.items():
        density = len(ws)
        excitement = sum(1 for w in ws if w["word"].lower().strip(".,!?") in EXCITEMENT_WORDS)
        score = density + excitement * 5
        scored.append((idx, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    keep_idxs = set()
    for idx, _ in scored[: max(1, int(len(scored) * 0.4))]:
        keep_idxs.update({idx - 1, idx, idx + 1})

    kept_words = [w for w in words if int(w["start"] // window) in keep_idxs]
    kept_words.sort(key=lambda w: w["start"])
    return transcribe_mod.words_to_plaintext_with_timestamps(kept_words)


def main():
    t0 = time.time()

    video_url = os.environ.get("VIDEO_URL", "").strip()
    local_video_path = os.environ.get("LOCAL_VIDEO_PATH", "").strip()
    guidelines_file = os.environ.get("GUIDELINES_FILE", "guidelines/example_guidelines.txt")
    num_clips = int(os.environ.get("NUM_CLIPS", "5"))

    os.makedirs("output", exist_ok=True)

    print("== Step 1/5: Fetching video ==")
    video_path = fetch.get_video(video_url, local_video_path)
    duration = get_video_duration(video_path)
    print(f"Video duration: {duration:.0f}s")

    print("== Step 2/5: Transcribing (local whisper.cpp) ==")
    words = transcribe_mod.transcribe(video_path)
    full_transcript_text = transcribe_mod.words_to_plaintext_with_timestamps(words)
    llm_transcript_text = sample_transcript_if_long(words, duration, full_transcript_text)

    print("== Step 3/5: Selecting best moments (local LLM) ==")
    clips_meta = select_mod.select_moments(llm_transcript_text, num_clips=num_clips)
    if not clips_meta:
        raise RuntimeError("No valid clips were selected -- try a different whisper model or check the transcript.")
    print(f"Selected {len(clips_meta)} clips.")

    print("== Step 4/5: Rendering clips (ffmpeg: cut, crop to 9:16, captions) ==")
    report_clips = []
    for i, clip in enumerate(clips_meta, start=1):
        out_path = f"output/clip_{i}.mp4"
        render_mod.render_clip(
            video_path, words, clip["start_seconds"], clip["end_seconds"], out_path
        )

        clip_words = [w for w in words if clip["start_seconds"] <= w["start"] < clip["end_seconds"]]
        clip_transcript = " ".join(w["word"] for w in clip_words)
        clip_duration = clip["end_seconds"] - clip["start_seconds"]

        print(f"== Step 5/5: Inspecting clip {i} against guidelines ==")
        checklist = inspector_mod.inspect_clip(guidelines_file, clip_transcript, clip_duration)

        report_clips.append({
            "file": out_path,
            "hook_title": clip.get("hook_title", ""),
            "virality_score": clip.get("virality_score", ""),
            "reasoning": clip.get("reasoning", ""),
            "start": clip["start_seconds"],
            "end": clip["end_seconds"],
            "duration": clip_duration,
            "transcript": clip_transcript,
            "checklist": checklist,
        })

    with open("output/report.json", "w", encoding="utf-8") as f:
        json.dump(report_clips, f, indent=2)

    write_markdown_report(report_clips)

    elapsed = time.time() - t0
    print(f"Done in {elapsed:.0f}s ({elapsed/60:.1f} min).")


def write_markdown_report(report_clips: list[dict]):
    lines = ["# AI Clipper Report\n"]
    for i, c in enumerate(report_clips, start=1):
        lines.append(f"## Clip {i}: {c['hook_title']}")
        lines.append(f"- File: `{c['file']}`")
        lines.append(f"- Timestamp: {c['start']:.0f}s - {c['end']:.0f}s ({c['duration']:.0f}s)")
        lines.append(f"- Virality score: {c['virality_score']}/10")
        lines.append(f"- Why this moment: {c['reasoning']}")
        lines.append("\n**AI Inspector checklist:**\n")
        for item in c["checklist"]:
            box = "[x]" if item.get("pass") else "[ ]"
            lines.append(f"- {box} {item.get('rule', '')} -- {item.get('reason', '')}")
        lines.append("")
    with open("output/report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
