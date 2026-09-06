"""
The "expert clipper" brain. Feeds the timestamped transcript to the local
LLM and asks it to behave like a professional short-form video editor:
find hooks, emotional peaks, punchlines, cliffhangers, strong opinions, and
payoff moments, then return 30-60s clip windows ranked by predicted
engagement.

Customize the heuristics below to match your own taste / niche.
"""
import re
import llm

CLIPPER_SYSTEM_PROMPT = """\
You are a world-class short-form video editor who has clipped viral moments
for major streamers and podcasts. You've studied thousands of clips that hit
millions of views and you know exactly what makes someone stop scrolling and
watch to the end. You look for:

- A strong HOOK in the first 1-3 seconds (a bold claim, a question, a
  surprising statement, or a mid-action moment) that creates a curiosity gap.
- Emotional peaks: laughter, anger, shock, vulnerability, excitement.
- Punchlines, comebacks, or a clear "payoff" to a setup.
- Cliffhangers or unresolved tension that makes people want the full video.
- Strong, quotable, or mildly controversial opinions that spark comments.
- A clean self-contained arc: the clip should make sense without context
  from the rest of the video, and should NOT start or end mid-sentence.
- Clips must be between 30 and 60 seconds long.
- Clips must not overlap with each other.

You are ruthless about cutting anything slow, rambling, or context-dependent.
"""

USER_PROMPT_TEMPLATE = """\
Here is a timestamped transcript of a video (format: [MM:SS] then words
spoken from that point):

---
{transcript}
---

Pick the {num_clips} best moments for short-form vertical clips (TikTok/
Shorts/Reels), following your expert judgment described above.

Respond with ONLY a JSON array, no prose, no markdown fences, in this exact
shape. Timestamps MUST be in MM:SS format (e.g. "04:12"). Keep "reasoning"
to under 15 words so your response stays short and complete:

[
  {{
    "start_time": "MM:SS",
    "end_time": "MM:SS",
    "hook_title": "a punchy 6-10 word title for this clip",
    "virality_score": 1-10,
    "reasoning": "short reason, under 15 words"
  }}
]
"""


def timestamp_to_seconds(ts) -> float:
    """Parses MM:SS, H:MM:SS, or a bare number of seconds. Tolerant of
    stray whitespace/characters a small local LLM might add."""
    if isinstance(ts, (int, float)):
        return float(ts)

    ts = str(ts).strip()
    # Keep only digits, colons, and dots (strips stray text like "~" or "s").
    ts = re.sub(r"[^0-9:.]", "", ts)
    if not ts:
        raise ValueError(f"Empty/unparseable timestamp: {ts!r}")

    parts = [float(p) for p in ts.split(":") if p != ""]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        m, s = parts
        return m * 60 + s
    if len(parts) == 3:
        h, m, s = parts
        return h * 3600 + m * 60 + s
    raise ValueError(f"Unrecognized timestamp format: {ts}")


def _dedupe_overlaps(clips: list) -> list:
    """Greedily keep highest-scoring clips, dropping any that overlap an
    already-accepted clip in time."""
    ranked = sorted(clips, key=lambda c: c.get("virality_score", 0), reverse=True)
    accepted = []
    for c in ranked:
        s, e = c["start_seconds"], c["end_seconds"]
        if any(not (e <= a["start_seconds"] or s >= a["end_seconds"]) for a in accepted):
            continue
        accepted.append(c)
    return accepted


def _fallback_evenly_spaced_clips(transcript_text: str, num_clips: int, clip_length: float = 45.0) -> list:
    """
    Safety net: if the LLM's response couldn't be turned into any valid
    clips (bad format, all filtered out, etc.), fall back to evenly spaced
    windows across the video rather than crashing the whole pipeline.
    Uses the last timestamp seen in the transcript to estimate duration.
    """
    timestamps = re.findall(r"\[(\d{2}):(\d{2})\]", transcript_text)
    if not timestamps:
        raise RuntimeError(
            "Could not select clips: the LLM's response was unusable and no "
            "timestamps were found in the transcript to build a fallback."
        )
    last_m, last_s = timestamps[-1]
    total_seconds = int(last_m) * 60 + int(last_s)

    print("WARNING: LLM moment selection failed validation -- using evenly "
          "spaced fallback clips instead. Check the LLM's raw output above "
          "if this keeps happening.")

    clips = []
    usable_span = max(total_seconds - clip_length, clip_length)
    step = usable_span / max(num_clips, 1)
    for i in range(num_clips):
        start = i * step
        end = start + clip_length
        clips.append({
            "start_time": f"{int(start//60):02d}:{int(start%60):02d}",
            "end_time": f"{int(end//60):02d}:{int(end%60):02d}",
            "hook_title": f"Clip {i + 1}",
            "virality_score": 5,
            "reasoning": "Fallback: evenly spaced (LLM selection failed).",
            "start_seconds": start,
            "end_seconds": end,
        })
    return clips


def select_moments(transcript_text: str, num_clips: int = 5) -> list:
    prompt = (
        f"<|im_start|>system\n{CLIPPER_SYSTEM_PROMPT}<|im_end|>\n"
        f"<|im_start|>user\n{USER_PROMPT_TEMPLATE.format(transcript=transcript_text, num_clips=num_clips)}<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )

    try:
        raw_clips = llm.ask_json(prompt, max_tokens=3000, temperature=0.3)
    except ValueError as e:
        print(f"WARNING: LLM did not return valid JSON: {e}")
        raw_clips = []

    if not isinstance(raw_clips, list):
        print(f"WARNING: Expected a JSON list of clips, got: {raw_clips!r}")
        raw_clips = []

    print(f"LLM returned {len(raw_clips)} raw candidate clip(s).")

    clips = []
    for i, c in enumerate(raw_clips):
        try:
            start_s = timestamp_to_seconds(c["start_time"])
            end_s = timestamp_to_seconds(c["end_time"])
        except (KeyError, ValueError, TypeError) as e:
            print(f"  Skipping candidate {i}: bad timestamp ({e}). Raw: {c!r}")
            continue
        duration = end_s - start_s
        if duration <= 0:
            print(f"  Skipping candidate {i}: non-positive duration ({duration}s).")
            continue
        # Slightly more forgiving than the strict 30-60s spec, so small LLM
        # drift doesn't throw away an otherwise-good pick.
        if duration < 20 or duration > 75:
            print(f"  Skipping candidate {i}: duration {duration:.0f}s outside allowed range.")
            continue
        clips.append({
            **c,
            "start_seconds": start_s,
            "end_seconds": end_s,
        })

    clips = _dedupe_overlaps(clips)

    if not clips:
        clips = _fallback_evenly_spaced_clips(transcript_text, num_clips)

    clips = sorted(clips, key=lambda c: c.get("virality_score", 0), reverse=True)[:num_clips]
    return sorted(clips, key=lambda c: c["start_seconds"])