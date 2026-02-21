import base64
import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Iterable, Optional

import requests


@dataclass
class FrameItem:
    frame_index: int
    timestamp_s: float
    jpeg_path: Path


def extract_frames_from_chunk(
    chunk_path: str,
    out_dir: str,
    fps: float = 0.5,  # 0.5 fps = 1 frame every 2 seconds
) -> List[FrameItem]:
    """
    Extracts JPEG frames from a video chunk at a fixed FPS.
    Returns FrameItem list (index, timestamp, path).
    """
    chunk = Path(chunk_path).resolve()
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    # Extract frames
    # -vf fps=... controls sampling rate
    # -q:v sets JPEG quality (2 is high quality)
    pattern = out / "frame_%05d.jpg"
    cmd = [
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(chunk),
        "-vf", f"fps={fps}",
        "-q:v", "2",
        str(pattern),
    ]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg frame extraction failed:\n{p.stderr}")

    # Get timestamps for each extracted frame via fps spacing
    # timestamp for frame i ≈ i / fps
    frame_files = sorted(out.glob("frame_*.jpg"))
    frames: List[FrameItem] = []
    for i, f in enumerate(frame_files):
        ts = (i / fps) if fps > 0 else 0.0
        frames.append(FrameItem(frame_index=i, timestamp_s=round(ts, 3), jpeg_path=f))

    return frames


def batch_iter(items: List[Any], batch_size: int) -> Iterable[List[Any]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be > 0")
    for i in range(0, len(items), batch_size):
        yield items[i:i + batch_size]


def _jpeg_to_base64(jpeg_path: Path) -> str:
    b = jpeg_path.read_bytes()
    return base64.b64encode(b).decode("utf-8")


def build_batch_payload(
    frames: List[FrameItem],
    prompt: str,
) -> Dict[str, Any]:
    """
    Builds a payload containing multiple images + metadata.
    Your server should return one description per image.
    """
    images_b64 = [_jpeg_to_base64(f.jpeg_path) for f in frames]
    meta = [{"frame_index": f.frame_index, "timestamp_s": f.timestamp_s} for f in frames]

    return {
        "prompt": prompt,
        "images_b64": images_b64,
        "meta": meta,
    }


def send_batch_to_ollama_vision(
    payload: Dict[str, Any],
    endpoint_url: str,
    timeout_s: int = 120,
) -> List[Dict[str, Any]]:
    """
    Sends ONE request for an entire batch.

    Expected server response format (recommended):
    {
      "results": [
        {"frame_index": 0, "timestamp_s": 0.0, "caption": "...", "text_seen": "..."},
        ...
      ]
    }

    If your endpoint returns a different format, adjust parsing below.
    """
    r = requests.post(endpoint_url, json=payload, timeout=timeout_s)
    r.raise_for_status()
    data = r.json()

    if "results" not in data or not isinstance(data["results"], list):
        raise ValueError(f"Unexpected response format: {data}")

    return data["results"]


def process_chunk_with_batching(
    chunk_path: str,
    frames_dir: str,
    endpoint_url: str,
    *,
    fps: float = 0.5,
    batch_size: int = 10,
) -> List[Dict[str, Any]]:
    """
    End-to-end batching for one video chunk:
    - extract frames
    - group into batches
    - send each batch in ONE request
    - collect per-frame outputs
    """
    frames = extract_frames_from_chunk(chunk_path, frames_dir, fps=fps)

    prompt = (
        "For each image, describe what the user is looking at, and extract any readable text "
        "(prices, labels, signs). Return one JSON object per image."
    )

    all_results: List[Dict[str, Any]] = []
    for batch in batch_iter(frames, batch_size=batch_size):
        payload = build_batch_payload(batch, prompt=prompt)
        batch_results = send_batch_to_ollama_vision(payload, endpoint_url=endpoint_url)
        all_results.extend(batch_results)

    return all_results


if __name__ == "__main__":
    results = process_chunk_with_batching(
        chunk_path=r"C:\Users\ahnaf\Desktop\entropy-hacked-2026\chunks\chunk_00000.mp4",
        frames_dir=r"C:\Users\ahnaf\Desktop\entropy-hacked-2026\frames\chunk_00000",
        endpoint_url="https://YOUR_OLLAMA_SERVER/vision/batch",
        fps=0.5,
        batch_size=10,
    )
    print(json.dumps(results, indent=2))