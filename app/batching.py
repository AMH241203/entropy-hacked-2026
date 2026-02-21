import base64
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

try:
    import requests
except ModuleNotFoundError:  # optional in offline/test environments
    requests = None


@dataclass
class FrameItem:
    frame_index: int
    timestamp_s: float
    jpeg_path: Path


def _run(cmd: List[str]) -> None:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{p.stderr}")


def extract_frames_from_chunk(
    chunk_path: str,
    out_dir: str,
    fps: float = 0.5,
) -> List[FrameItem]:
    chunk = Path(chunk_path).resolve()
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    pattern = out / "frame_%05d.jpg"
    _run([
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        str(chunk),
        "-vf",
        f"fps={fps}",
        "-q:v",
        "2",
        str(pattern),
    ])

    frame_files = sorted(out.glob("frame_*.jpg"))
    frames: List[FrameItem] = []
    for i, f in enumerate(frame_files):
        ts = (i / fps) if fps > 0 else 0.0
        frames.append(FrameItem(frame_index=i, timestamp_s=round(ts, 3), jpeg_path=f))
    return frames


def extract_audio_from_chunk(
    chunk_path: str,
    out_audio_path: str,
    *,
    sample_rate: int = 16000,
    channels: int = 1,
) -> Path:
    out_path = Path(out_audio_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _run([
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        str(Path(chunk_path).resolve()),
        "-vn",
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate),
        str(out_path),
    ])
    return out_path


def batch_iter(items: List[Any], batch_size: int) -> Iterable[List[Any]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be > 0")
    for i in range(0, len(items), batch_size):
        yield items[i : i + batch_size]


def _jpeg_to_base64(jpeg_path: Path) -> str:
    return base64.b64encode(jpeg_path.read_bytes()).decode("utf-8")


def build_batch_payload(frames: List[FrameItem], prompt: str) -> Dict[str, Any]:
    images_b64 = [_jpeg_to_base64(f.jpeg_path) for f in frames]
    meta = [{"frame_index": f.frame_index, "timestamp_s": f.timestamp_s} for f in frames]
    return {"prompt": prompt, "images_b64": images_b64, "meta": meta}


def send_batch_to_ollama_vision(
    payload: Dict[str, Any],
    endpoint_url: str,
    timeout_s: int = 120,
    *,
    session: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    if session is None and requests is None:
        raise RuntimeError("requests is required to send HTTP batches")
    client = session or requests
    r = client.post(endpoint_url, json=payload, timeout=timeout_s)
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
    max_workers: int = 1,
    sender: Optional[Callable[[Dict[str, Any], str], List[Dict[str, Any]]]] = None,
) -> List[Dict[str, Any]]:
    frames = extract_frames_from_chunk(chunk_path, frames_dir, fps=fps)
    prompt = (
        "For each image, describe what the user is looking at, and extract any readable text "
        "(prices, labels, signs). Return one JSON object per image."
    )
    send_fn = sender or send_batch_to_ollama_vision

    batches = list(batch_iter(frames, batch_size=batch_size))

    def _send(batch: List[FrameItem]) -> List[Dict[str, Any]]:
        payload = build_batch_payload(batch, prompt=prompt)
        return send_fn(payload, endpoint_url)

    all_results: List[Dict[str, Any]] = []
    if max_workers <= 1:
        for batch in batches:
            all_results.extend(_send(batch))
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            for result in pool.map(_send, batches):
                all_results.extend(result)

    return sorted(all_results, key=lambda item: item.get("frame_index", 0))


if __name__ == "__main__":
    results = process_chunk_with_batching(
        chunk_path=r"C:\Users\ahnaf\Desktop\entropy-hacked-2026\chunks\chunk_00000.mp4",
        frames_dir=r"C:\Users\ahnaf\Desktop\entropy-hacked-2026\frames\chunk_00000",
        endpoint_url="https://YOUR_OLLAMA_SERVER/vision/batch",
        fps=0.5,
        batch_size=10,
    )
    print(json.dumps(results, indent=2))