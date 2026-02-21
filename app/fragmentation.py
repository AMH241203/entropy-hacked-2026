import json
import shutil
import subprocess
from pathlib import Path
from typing import List, Dict, Any


def _run(cmd: List[str]) -> None:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            + " ".join(cmd)
            + "\n\nSTDERR:\n"
            + (p.stderr[-4000:] if p.stderr else "")
        )


def _ffprobe_duration_seconds(video_path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        str(video_path),
    ]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe failed:\n{p.stderr}")
    data = json.loads(p.stdout)
    return float(data["format"]["duration"])


def chunk_video(
    input_video: str,
    out_dir: str,
    chunk_seconds: int = 30,
    *,
    exact_boundaries: bool = False,
) -> List[Dict[str, Any]]:
    """
    Splits a video into smaller chunks.

    - exact_boundaries=False (default): FAST, no re-encode, but cuts occur on keyframes (boundaries may drift slightly).
    - exact_boundaries=True: Re-encodes and forces keyframes at chunk boundaries to get precise 10s/30s/etc cuts.

    Returns a manifest list with: {index, start_s, end_s, path}
    """
    if not (10 <= chunk_seconds <= 60):
        raise ValueError("chunk_seconds must be between 10 and 60")

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise EnvironmentError("ffmpeg/ffprobe not found on PATH. Install FFmpeg and try again.")
    
    input_path = Path(input_video).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input video not found: {input_path}")

    out_path = Path(out_dir).expanduser().resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    # Optional: clear existing chunks
    # for f in out_path.glob("chunk_*.mp4"):
    #     f.unlink()

    segment_list = out_path / "segments.csv"
    output_pattern = out_path / "chunk_%05d.mp4"

    if not exact_boundaries:
        # Fast split (no re-encode). Cuts happen at the nearest keyframe.
        cmd = [
            "ffmpeg",
            "-hide_banner", "-y",
            "-i", str(input_path),
            "-map", "0",
            "-c", "copy",
            "-f", "segment",
            "-segment_time", str(chunk_seconds),
            "-reset_timestamps", "1",
            "-segment_list", str(segment_list),
            "-segment_list_type", "csv",
            str(output_pattern),
        ]
        _run(cmd)
    else:
        # Exact split: re-encode and force keyframes at chunk boundaries.
        # This produces accurate chunk durations (10s/30s/etc).
        cmd = [
            "ffmpeg",
            "-hide_banner", "-y",
            "-i", str(input_path),
            "-map", "0",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-force_key_frames", f"expr:gte(t,n_forced*{chunk_seconds})",
            "-c:a", "aac",
            "-b:a", "128k",
            "-f", "segment",
            "-segment_time", str(chunk_seconds),
            "-reset_timestamps", "1",
            "-segment_list", str(segment_list),
            "-segment_list_type", "csv",
            str(output_pattern),
        ]
        _run(cmd)

    # Build a manifest with approximate start/end times.
    duration = _ffprobe_duration_seconds(input_path)
    chunk_files = sorted(out_path.glob("chunk_*.mp4"))

    manifest: List[Dict[str, Any]] = []
    for i, f in enumerate(chunk_files):
        start_s = i * chunk_seconds
        end_s = min((i + 1) * chunk_seconds, duration)
        manifest.append(
            {"index": i, "start_s": round(start_s, 3), "end_s": round(end_s, 3), "path": str(f)}
        )

    (out_path / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    m = chunk_video(
    input_video=r"C:\Users\ahnaf\Desktop\entropy-hacked-2026\2 - Search Problems_10min.mkv",
    out_dir="chunks",
    chunk_seconds=20,
    exact_boundaries=True,
    )
    print(f"Created {len(m)} chunks. Manifest saved to chunks/manifest.json")