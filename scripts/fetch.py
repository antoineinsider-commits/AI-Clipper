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
    cmd = [
        "yt-dlp",
        "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "--merge-output-format", "mp4",
        "-o", out_template,
        video_url,
    ]
    subprocess.run(cmd, check=True)

    # Find whatever file yt-dlp produced.
    for f in os.listdir(out_dir):
        if f.startswith("source."):
            return os.path.join(out_dir, f)

    raise RuntimeError("yt-dlp did not produce an output file.")
