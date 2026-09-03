"""
The "expert clipper" brain. Feeds the timestamped transcript to the local
LLM and asks it to behave like a professional short-form video editor:
find hooks, emotional peaks, punchlines, cliffhangers, strong opinions, and
payoff moments, then return 30-60s clip windows ranked by predicted
engagement.

Customize the heuristics below to match your own taste / niche.
"""
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
shape:

[
  {{
    "start_time": "MM:SS",
    "end_time": "MM:SS",
    "hook_title": "a punchy 6-10 word title for this clip",
    "virality_score": 1-10,
    "reasoning": "one or two sentences on why this moment works"
  }}
]
"""


def timestamp_to_seconds(ts: str) -> float:
    parts = [float(p) for p in ts.split(":")]
    if len(parts) == 2:
        m, s = parts
        return m * 60 + s
    if len(parts) == 3:
        h, m, s = parts
        return h * 3600 + m * 60 + s
    raise ValueError(f"Unrecognized timestamp format: {ts}")


def _dedupe_overlaps(clips: list[dict]) -> list[dict]:
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


def select_moments(transcript_text: str, num_clips: int = 5) -> list[dict]:
    prompt = (
        f"<|im_start|>system\n{CLIPPER_SYSTEM_PROMPT}<|im_end|>\n"
        f"<|im_start|>user\n{USER_PROMPT_TEMPLATE.format(transcript=transcript_text, num_clips=num_clips)}<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )

    raw_clips = llm.ask_json(prompt, max_tokens=2000)
    if not isinstance(raw_clips, list):
        raise ValueError(f"Expected a JSON list of clips, got: {raw_clips}")

    clips = []
    for c in raw_clips:
        try:
            start_s = timestamp_to_seconds(c["start_time"])
            end_s = timestamp_to_seconds(c["end_time"])
        except (KeyError, ValueError):
            continue
        duration = end_s - start_s
        if duration <= 0:
            continue
        # Enforce the 30-60s constraint even if the model drifts slightly.
        if duration < 25 or duration > 65:
            continue
        clips.append({
            **c,
            "start_seconds": start_s,
            "end_seconds": end_s,
        })

    clips = _dedupe_overlaps(clips)
    clips = sorted(clips, key=lambda c: c.get("virality_score", 0), reverse=True)[:num_clips]
    # Re-sort chronologically for a nicer final report.
    return sorted(clips, key=lambda c: c["start_seconds"])
