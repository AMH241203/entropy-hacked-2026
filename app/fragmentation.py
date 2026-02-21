import csv
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


CHUNK_GLOB = "chunk_*.mp4"


def _run(cmd: List[str]) -> None:
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            + " ".join(cmd)
            + "\n\nSTDERR:\n"
            + (proc.stderr[-4000:] if proc.stderr else "")
        )


def _ffprobe_duration_seconds(video_path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(video_path),
    ]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe failed:\n{p.stderr}")
    data = json.loads(p.stdout)
    return float(data["format"]["duration"])


def cleanup_chunk_files(out_dir: str, *, remove_manifest: bool = False) -> int:
    out_path = Path(out_dir).expanduser().resolve()
    if not out_path.exists():
        return 0

    deleted = 0
    for pattern in (CHUNK_GLOB, "segments.csv"):
        for file_path in out_path.glob(pattern):
            file_path.unlink(missing_ok=True)
            deleted += 1

    if remove_manifest:
        manifest = out_path / "manifest.json"
        if manifest.exists():
            manifest.unlink()
            deleted += 1

    return deleted


def _read_segment_timings(segment_list: Path) -> List[Dict[str, Any]]:
    if not segment_list.exists():
        return []

    rows: List[Dict[str, Any]] = []
    with segment_list.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        for index, row in enumerate(reader):
            if len(row) < 3:
                continue
            try:
                start_s = float(row[1])
                end_s = float(row[2])
            except ValueError:
                continue
            rows.append(
                {
                    "index": index,
                    "start_s": round(start_s, 3),
                    "end_s": round(end_s, 3),
                    "path": str((segment_list.parent / row[0]).resolve()),
                }
            )
    return rows


def write_manifest(
    out_dir: str,
    *,
    chunk_seconds: int,
    duration_s: Optional[float] = None,
    segment_list: Optional[str] = None,
) -> List[Dict[str, Any]]:
    out_path = Path(out_dir).expanduser().resolve()
    source_segments = Path(segment_list).resolve() if segment_list else out_path / "segments.csv"

    manifest = _read_segment_timings(source_segments)
    if not manifest:
        chunk_files = sorted(out_path.glob(CHUNK_GLOB))
        if duration_s is None:
            raise ValueError("duration_s is required when no segment_list is available")

        manifest = []
        for i, chunk_path in enumerate(chunk_files):
            start_s = i * chunk_seconds
            end_s = min((i + 1) * chunk_seconds, duration_s)
            manifest.append(
                {
                    "index": i,
                    "start_s": round(start_s, 3),
                    "end_s": round(end_s, 3),
                    "path": str(chunk_path.resolve()),
                }
            )

    manifest_path = out_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def chunk_video(
    input_video: str,
    out_dir: str,
    chunk_seconds: int = 30,
    *,
    exact_boundaries: bool = False,
    cleanup_existing: bool = False,
    keep_segment_list: bool = False,
) -> List[Dict[str, Any]]:
    if not (10 <= chunk_seconds <= 60):
        raise ValueError("chunk_seconds must be between 10 and 60")

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise EnvironmentError("ffmpeg/ffprobe not found on PATH. Install FFmpeg and try again.")

    input_path = Path(input_video).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input video not found: {input_path}")

    out_path = Path(out_dir).expanduser().resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    if cleanup_existing:
        cleanup_chunk_files(str(out_path))

    segment_list = out_path / "segments.csv"
    output_pattern = out_path / "chunk_%05d.mp4"

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        str(input_path),
        "-map",
        "0",
    ]

    if not exact_boundaries:
        cmd.extend(["-c", "copy"])
    else:
        cmd.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-force_key_frames",
                f"expr:gte(t,n_forced*{chunk_seconds})",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
            ]
        )

    cmd.extend(
        [
            "-f",
            "segment",
            "-segment_time",
            str(chunk_seconds),
            "-reset_timestamps",
            "1",
            "-segment_list",
            str(segment_list),
            "-segment_list_type",
            "csv",
            str(output_pattern),
        ]
    )
    _run(cmd)

    manifest = write_manifest(
        str(out_path),
        chunk_seconds=chunk_seconds,
        duration_s=_ffprobe_duration_seconds(input_path),
        segment_list=str(segment_list),
    )

    if not keep_segment_list and segment_list.exists():
        segment_list.unlink()

    return manifest