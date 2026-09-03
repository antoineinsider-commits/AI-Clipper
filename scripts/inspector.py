"""
The AI Inspector: given a plain-language guidelines file (one rule per
line) and a clip's transcript, produces a tickbox-style pass/fail
checklist with a short reason for each rule. This is what you'd hand to a
streamer/brand to prove a clip is on-guideline before it goes out.
"""
import llm


INSPECTOR_PROMPT_TEMPLATE = """\
You are a strict content compliance reviewer. A client has given you a list
of guidelines that every clip must follow. You will be shown the transcript
of one clip and must check it against EVERY guideline individually.

Guidelines (one per line):
---
{guidelines}
---

Clip transcript:
---
{transcript}
---

Clip duration: {duration:.0f} seconds.

For EVERY guideline listed above, decide PASS or FAIL and give a one-sentence
reason grounded in the actual transcript content (or duration, for length
rules). Be strict: if you are not confident it passes, mark it FAIL and
explain what's missing or uncertain.

Respond with ONLY a JSON array, no prose, no markdown fences, in this exact
shape:

[
  {{"rule": "<the exact guideline text>", "pass": true, "reason": "..."}},
  {{"rule": "<the exact guideline text>", "pass": false, "reason": "..."}}
]
"""


def load_guidelines(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def inspect_clip(guidelines_path: str, clip_transcript: str, duration_seconds: float) -> list[dict]:
    guidelines = load_guidelines(guidelines_path)
    guidelines_block = "\n".join(f"- {g}" for g in guidelines)

    prompt = (
        "<|im_start|>system\nYou are a meticulous, literal-minded compliance checker.<|im_end|>\n"
        f"<|im_start|>user\n{INSPECTOR_PROMPT_TEMPLATE.format(guidelines=guidelines_block, transcript=clip_transcript, duration=duration_seconds)}<|im_end|>\n"
        "<|im_start|>assistant\n"
    )

    results = llm.ask_json(prompt, max_tokens=1200)
    if not isinstance(results, list):
        raise ValueError(f"Expected a JSON list from inspector, got: {results}")
    return results
