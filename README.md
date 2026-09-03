# AI Clipper 🎬

Turn a long video (or a link to one) into 5 high-retention, vertical, captioned
clips — plus an "AI Inspector" compliance checklist — all running for free
inside a **GitHub Actions** job. No paid APIs. Everything runs locally on the
runner: whisper.cpp for transcription, a small local LLM (via
`llama-cpp-python`) for moment-picking and compliance checking, and ffmpeg for
cutting/cropping/captioning.

## What it does

1. **Ingests** a video — either a direct file you upload to the workflow, or
   a URL (YouTube, Twitch VOD, etc.) fetched with `yt-dlp`.
2. **Transcribes** it locally with `whisper.cpp`, producing word-level
   timestamps (no audio ever leaves the runner).
3. **Analyzes** the transcript with a local LLM acting as an "expert clipper"
   — it looks for hooks, emotional peaks, punchlines, cliffhangers,
   controversy, strong opinions, and payoff moments, and picks 5 non-
   overlapping 30–60s windows ranked by predicted engagement.
4. **Renders** each clip: cuts the segment, crops/pads to vertical 9:16,
   normalizes audio, and burns in animated, karaoke-style word captions.
5. **Inspects** each clip against your own guidelines (a plain text file you
   provide, e.g. "no profanity", "must mention the sponsor", "under 60s",
   "on-brand tone") and produces a pass/fail checklist with reasoning for
   every rule, per clip.
6. **Outputs** everything as downloadable GitHub Actions artifacts: 5 `.mp4`
   files + a `report.md` with the checklist and the clip metadata (title
   suggestion, virality score, timestamps, why it was picked).

## Repo layout

```
.github/workflows/clip.yml   # the GitHub Actions workflow (the "run button")
scripts/
  pipeline.py                # orchestrates the whole run, enforces the time budget
  fetch.py                   # yt-dlp download / local file handling
  transcribe.py              # whisper.cpp wrapper -> word-level JSON transcript
  select_moments.py          # local LLM: picks 5 clip windows
  render_clip.py             # ffmpeg: cut, crop to 9:16, burn captions
  inspector.py                # local LLM: guideline compliance checklist
  llm.py                      # shared llama-cpp-python wrapper
guidelines/example_guidelines.txt
requirements.txt
```

## Setup (one-time)

1. Fork / clone this repo.
2. That's it — no secrets, no API keys. Model files are downloaded
   automatically by the workflow the first time it runs (and cached after
   that using `actions/cache`).

## Running it

Go to **Actions → AI Clipper → Run workflow** and fill in the inputs:

| Input | Example | Notes |
|---|---|---|
| `video_url` | `https://youtube.com/watch?v=...` | Leave blank if uploading a file instead |
| `guidelines_file` | `guidelines/example_guidelines.txt` | Path to your rules file in the repo, or paste guidelines inline |
| `num_clips` | `5` | Default 5 |
| `whisper_model` | `base.en` | `tiny.en` (fastest) / `base.en` (default) / `small.en` (best quality, slower) |

To use a **local file** instead of a URL: commit/upload it to the repo under
`input/` (or use `workflow_dispatch` with a repo-hosted path), and leave
`video_url` blank.

When it finishes, download the `clips` artifact from the run summary page —
it contains the 5 `.mp4` files and `report.md`.

## Time budget & honesty check

- `tiny.en`/`base.en` whisper models transcribe roughly 5–10x faster than
  realtime on a 2-core CPU runner. A 20–30 min video should transcribe in
  well under a minute.
- The local LLM (default: a 3B quantized instruct model, ~2GB) analyzing a
  30-minute transcript takes roughly 1–3 minutes on CPU.
- Rendering 5 clips with ffmpeg (cut + crop + caption burn, no re-encoding
  of the whole source) typically takes 1–3 minutes total.
- **For videos over ~45–60 minutes**, the pipeline automatically switches to
  "sampling mode": it transcribes the full audio (transcription is cheap)
  but chunks the transcript and only sends the LLM the highest-density
  sections (based on speech rate, laughter/applause audio cues, and
  keyword scoring) to stay inside the time budget. This is a real trade-off
  — for very long streams, the LLM sees a strong sample of the video, not
  100% of it.

## Customizing the "expert clipper" judgment

Edit the prompt in `scripts/select_moments.py` — it's a plain text template.
Add your own heuristics (e.g. "prioritize moments with a clear question or
cliffhanger in the last 5 seconds" or "avoid clips that start mid-sentence").

## Customizing the Inspector's guidelines

Guidelines are just a plain-language text file, one rule per line, e.g.:

```
Must not mention any competitor brand names.
Must include a clear hook in the first 3 seconds.
No profanity or slurs.
Clip length must be between 30 and 60 seconds.
Tone should match an energetic, upbeat streamer persona.
```

The Inspector LLM reads each clip's transcript + these rules and returns a
checkbox-style pass/fail with a one-line reason per rule, for every clip.
