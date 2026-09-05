"""
Resolves the input video to a local file path: either downloads it with
yt-dlp (URL case) or points directly at a repo-hosted file.
"""
import os
import subprocess


def get_video(video_url: str, local_video_path: str, out_dir: str = "work") -> str:
    os.makedirs(out_dir, exist_ok=True)

    if local_video_path:
        if not os.path.exists(local_video_path):
            raise FileNotFoundError(f"local_video_path does not exist: {local_video_path}")
        return local_video_path

    if not video_url:
        raise ValueError("Either video_url or local_video_path must be provided.")

    out_template = os.path.join(out_dir, "source.%(ext)s")

    base_cmd = [
        "yt-dlp",
        "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "--merge-output-format", "mp4",
        "-o", out_template,
    ]

    cookies_file = os.environ.get("YOUTUBE_COOKIES_FILE", "").strip()
    if cookies_file and os.path.exists(cookies_file):
        base_cmd += ["--cookies", cookies_file]

    # android/ios clients don't support cookies at all, so when we have
    # cookies, prioritize clients that actually use them.
    if cookies_file and os.path.exists(cookies_file):
        client_attempts = ["web", "mweb", "tv"]
    else:
        client_attempts = ["android", "ios", "tv_embedded", "web"]

    last_error = None
    for client in client_attempts:
        cmd = base_cmd + [
            "--extractor-args", f"youtube:player_client={client}",
            "--remote-components", "ejs:github",
            video_url,
        ]
        result = subprocess.run(cmd)
        if result.returncode == 0:
            last_error = None
            break
        last_error = result.returncode

    if last_error is not None:
        raise RuntimeError(
            "yt-dlp failed against all YouTube client fallbacks. "
            "YouTube is likely blocking this runner's IP and requires cookies. "
            "See README.md 'YouTube cookie auth' section for how to fix this."
        )

    # Find whatever file yt-dlp produced.
    for f in os.listdir(out_dir):
        if f.startswith("source."):
            return os.path.join(out_dir, f)

    raise RuntimeError("yt-dlp did not produce an output file.")