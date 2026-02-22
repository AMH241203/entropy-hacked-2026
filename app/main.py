from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.fragmentation import chunk_video

try:
    import requests
except ModuleNotFoundError:  # pragma: no cover
    requests = None

try:
    from faster_whisper import WhisperModel
except ModuleNotFoundError:  # pragma: no cover
    WhisperModel = None

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
CHUNKS_DIR = DATA_DIR / "chunks"
DB_PATH = DATA_DIR / "app.db"
STATIC_DIR = BASE_DIR / "app" / "static"

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/embeddings")
OLLAMA_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
EMBED_DIM = 64


class SearchService:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._whisper_model: Optional[Any] = None

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def setup(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS videos (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    upload_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    manifest_path TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id TEXT NOT NULL,
                    chunk_idx INTEGER NOT NULL,
                    start_s REAL NOT NULL,
                    end_s REAL NOT NULL,
                    chunk_path TEXT NOT NULL,
                    transcript TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    FOREIGN KEY(video_id) REFERENCES videos(id)
                )
                """
            )

    def create_video(self, filename: str, upload_path: Path) -> str:
        video_id = str(uuid.uuid4())
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO videos(id, filename, upload_path, status) VALUES (?, ?, ?, ?)",
                (video_id, filename, str(upload_path), "processing"),
            )
        return video_id

    def set_status(self, video_id: str, status: str, manifest_path: Optional[Path] = None) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE videos SET status = ?, manifest_path = COALESCE(?, manifest_path) WHERE id = ?",
                (status, str(manifest_path) if manifest_path else None, video_id),
            )

    def index_chunks(self, video_id: str, manifest: List[Dict[str, Any]]) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM chunks WHERE video_id = ?", (video_id,))

            for item in manifest:
                transcript = self._chunk_transcript(Path(item["path"]))
                embedding = self._embed_text(transcript)
                conn.execute(
                    """
                    INSERT INTO chunks(video_id, chunk_idx, start_s, end_s, chunk_path, transcript, embedding)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        video_id,
                        int(item["index"]),
                        float(item["start_s"]),
                        float(item["end_s"]),
                        str(item["path"]),
                        transcript,
                        json.dumps(embedding),
                    ),
                )

    def _chunk_transcript(self, chunk_path: Path) -> str:
        if WhisperModel is None:
            return f"Video chunk {chunk_path.stem.replace('_', ' ')}"

        if self._whisper_model is None:
            self._whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")

        segments, _ = self._whisper_model.transcribe(str(chunk_path), beam_size=1)
        transcript = " ".join(seg.text.strip() for seg in segments).strip()
        return transcript or f"Video chunk {chunk_path.stem.replace('_', ' ')}"

    def _embed_text(self, text: str) -> List[float]:
        if requests is not None:
            try:
                response = requests.post(
                    OLLAMA_URL,
                    json={"model": OLLAMA_MODEL, "prompt": text},
                    timeout=10,
                )
                response.raise_for_status()
                data = response.json()
                if isinstance(data.get("embedding"), list):
                    return [float(v) for v in data["embedding"]]
            except Exception:
                pass

        digest = hashlib.sha256(text.encode("utf-8")).digest()
        vals = []
        for i in range(EMBED_DIM):
            vals.append(((digest[i % len(digest)] / 255.0) * 2) - 1)
        return vals

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        query_vec = self._embed_text(query)
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT c.video_id, c.chunk_idx, c.start_s, c.end_s, c.chunk_path, c.transcript, c.embedding, v.filename
                FROM chunks c JOIN videos v ON v.id = c.video_id
                WHERE v.status = 'ready'
                """
            ).fetchall()

        scored: List[Dict[str, Any]] = []
        for row in rows:
            chunk_vec = json.loads(row["embedding"])
            score = self._cosine_similarity(query_vec, chunk_vec)
            snippet = row["transcript"][:180]
            scored.append(
                {
                    "video_id": row["video_id"],
                    "filename": row["filename"],
                    "chunk_idx": row["chunk_idx"],
                    "start_s": row["start_s"],
                    "end_s": row["end_s"],
                    "score": round(score, 4),
                    "snippet": snippet,
                    "clip_url": f"/clips/{row['video_id']}/{row['chunk_idx']}",
                }
            )

        return sorted(scored, key=lambda x: x["score"], reverse=True)[:limit]

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        n = min(len(a), len(b))
        if n == 0:
            return 0.0
        dot = sum(a[i] * b[i] for i in range(n))
        an = sum(a[i] * a[i] for i in range(n)) ** 0.5
        bn = sum(b[i] * b[i] for i in range(n)) ** 0.5
        if an == 0 or bn == 0:
            return 0.0
        return dot / (an * bn)

    def list_videos(self) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT id, filename, status FROM videos ORDER BY rowid DESC").fetchall()
        return [dict(row) for row in rows]

    def get_video_status(self, video_id: str) -> Dict[str, Any]:
        with self._conn() as conn:
            video = conn.execute("SELECT id, filename, status FROM videos WHERE id = ?", (video_id,)).fetchone()
            if video is None:
                raise HTTPException(status_code=404, detail="Video not found")
            chunks = conn.execute(
                "SELECT chunk_idx, start_s, end_s, chunk_path FROM chunks WHERE video_id = ? ORDER BY chunk_idx",
                (video_id,),
            ).fetchall()
        return {"video": dict(video), "chunks": [dict(row) for row in chunks]}

    def clip_path(self, video_id: str, chunk_idx: int) -> Path:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT chunk_path FROM chunks WHERE video_id = ? AND chunk_idx = ?",
                (video_id, chunk_idx),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Clip not found")
        return Path(row["chunk_path"])


service = SearchService(DB_PATH)
service.setup()

app = FastAPI(title="Entropy Memory Search")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/upload")
async def upload_video(file: UploadFile = File(...)) -> Dict[str, Any]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="filename required")

    safe_name = f"{uuid.uuid4()}_{Path(file.filename).name}"
    upload_path = UPLOAD_DIR / safe_name
    with upload_path.open("wb") as handle:
        handle.write(await file.read())

    video_id = service.create_video(file.filename, upload_path)
    video_chunk_dir = CHUNKS_DIR / video_id
    try:
        manifest = chunk_video(str(upload_path), str(video_chunk_dir), chunk_seconds=10, exact_boundaries=True)
        manifest_path = video_chunk_dir / "manifest.json"
        service.index_chunks(video_id, manifest)
        service.set_status(video_id, "ready", manifest_path=manifest_path)
    except Exception as exc:  # noqa: BLE001
        service.set_status(video_id, "failed")
        raise HTTPException(status_code=500, detail=f"processing failed: {exc}") from exc

    return {"video_id": video_id, "status": "ready", "chunks": len(manifest)}


@app.get("/videos")
def videos() -> Dict[str, Any]:
    return {"videos": service.list_videos()}


@app.get("/status/{video_id}")
def status(video_id: str) -> Dict[str, Any]:
    return service.get_video_status(video_id)


@app.get("/search")
def search(q: str = Query(..., min_length=1), limit: int = 5) -> Dict[str, Any]:
    return {"query": q, "results": service.search(q, limit=limit)}


@app.get("/clips/{video_id}/{chunk_idx}")
def clip(video_id: str, chunk_idx: int) -> FileResponse:
    return FileResponse(service.clip_path(video_id, chunk_idx), media_type="video/mp4")
