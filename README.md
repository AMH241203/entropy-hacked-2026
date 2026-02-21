# entropy-hacked-2026

## Hackathon Project Plan: Personal Day Memory Assistant (Phone Camera + Laptop)

This document is a **from-scratch implementation plan** for building a wearable-style memory system where:
- An **Android phone** acts as a dumb IP camera + microphone source.
- A **laptop** receives the stream, segments it, analyzes it with ML, stores memory events, and answers questions.

---

## 1) Define Scope and Hackathon Success Criteria

### Goal
Build a working prototype that can answer questions like:
- “What was the flight price I saw today?”
- “Who did I meet around 3 PM?”
- “Where did I leave my black notebook?”

### Minimum Viable Demo (MVP)
By demo time, ensure these work end-to-end:
1. Live phone stream received on laptop.
2. Stream is recorded in short fragments (e.g., 10–30 seconds).
3. Pipeline extracts:
   - speech transcript (ASR),
   - visual captions / objects / text (OCR),
   - timestamps.
4. Store everything in searchable memory store.
5. Q&A API/UI returns timestamped answer + confidence + source evidence.

### Non-goals for hackathon (defer)
- Perfect face recognition at scale.
- 24/7 battery-optimized mobile app.
- Full privacy policy/legal production hardening.

---

## 2) System Architecture (Phone + Laptop)

### Data Flow
1. **Android phone** streams video/audio over local network (RTSP/HTTP).
2. **Ingestion service on laptop** pulls stream and writes rolling video fragments.
3. **Batch/near-real-time workers** process each fragment:
   - keyframe extraction,
   - OCR,
   - object detection,
   - image caption/embedding,
   - speech transcription.
4. **Event fusion layer** merges outputs into timeline events.
5. **Memory DB + vector index** stores events + embeddings.
6. **Question answering service** retrieves relevant events and synthesizes final answer.

### Suggested Components
- Stream capture: `ffmpeg`.
- ASR: Whisper (faster-whisper or whisper.cpp).
- Vision:
  - OCR: PaddleOCR or EasyOCR.
  - Detection: YOLOv8.
  - Captioning/semantic embeddings: CLIP + optional LLM vision model.
- Storage:
  - Metadata: SQLite/Postgres.
  - Vectors: FAISS/Chroma/pgvector.
- API/UI: FastAPI + simple web chat page.

---

## 3) Detailed Step-by-Step Build Plan

## Phase A — Project Setup (Day 0 / Day 1)

1. **Initialize repository structure**
   - `ingest/` (stream + fragmentation)
   - `pipeline/` (ASR, OCR, vision)
   - `memory/` (schemas, retrieval)
   - `api/` (FastAPI endpoints)
   - `ui/` (optional lightweight chat page)
   - `configs/` (YAML for ports, model paths, thresholds)

2. **Set up Python environment**
   - Python 3.10+
   - Create virtualenv
   - Install baseline dependencies:
     - `fastapi`, `uvicorn`, `opencv-python`, `ffmpeg-python`
     - `faster-whisper`, `ultralytics`, `easyocr`
     - `sentence-transformers`, `faiss-cpu`, `sqlalchemy`, `pydantic`

3. **Create config file** (`configs/dev.yaml`)
   - stream URL, segment duration, storage paths
   - model device (`cpu`/`cuda`)
   - processing cadence and retention policy

4. **Set up logging and observability**
   - Structured logs with timestamps
   - Save per-fragment processing stats (latency, failures)

---

## Phase B — Phone Stream Ingestion (Core Input)

5. **Turn Android into dumb IP camera**
   - Use any IP camera app supporting RTSP/HTTP stream.
   - Keep phone + laptop on same Wi-Fi.
   - Lock camera orientation and disable sleep if possible.

6. **Verify stream from laptop**
   - Test command:
     - `ffplay <stream_url>`
   - Confirm both video and audio are available.

7. **Implement ingestion service**
   - `ingest/stream_capture.py`:
     - Pull stream continuously.
     - Handle reconnect logic for stream drops.

8. **Implement fragmenter**
   - Write HLS-like chunks or MP4 clips every 10–30 seconds.
   - Naming convention: `YYYYMMDD_HHMMSS_fragmentNN.mp4`.
   - Save fragment metadata (`start_ts`, `end_ts`, `path`) to DB.

9. **Add health endpoints**
   - `/health/stream` → last frame timestamp.
   - `/health/ingest` → queue depth, recent errors.

---

## Phase C — Per-Fragment ML Processing

10. **Extract keyframes**
   - Sample 1 frame/sec or scene-change-based extraction.
   - Store frame timestamps linked to fragment.

11. **Run OCR on keyframes**
   - Extract visible text (prices, signs, flight numbers).
   - Save text with bounding boxes + confidence + timestamp.

12. **Run object detection**
   - Use YOLO on keyframes.
   - Save objects (`label`, `confidence`, `timestamp`).

13. **Run scene/image captioning and embeddings**
   - Generate caption like “airport check-in counter with monitor showing fares”.
   - Create embedding vectors for semantic retrieval.

14. **Run audio transcription**
   - Extract audio from fragment.
   - Transcribe with Whisper.
   - Save token/segment timestamps.

15. **(Optional hackathon bonus) Speaker or face handling**
   - Lightweight face clustering (not full identity).
   - Store pseudo-IDs like `person_cluster_3`.

---

## Phase D — Memory Schema + Storage

16. **Define normalized schema**
   - `fragments`
   - `events` (canonical timeline event)
   - `observations` (OCR/object/transcript/caption rows)
   - `embeddings` (vector + reference id)

17. **Event fusion step**
   - For each time window, combine multimodal signals into a compact “memory event”:
     - timestamp range,
     - summary,
     - key entities (price, location, people, items),
     - evidence references.

18. **Index for retrieval**
   - Semantic vector index for natural-language queries.
   - Optional BM25 keyword index for exact terms like flight number or currency amount.

19. **Retention policy**
   - Keep full video only short-term (e.g., 24h–72h).
   - Keep compact structured events long-term.

---

## Phase E — Question Answering Layer

20. **Implement query parsing**
   - Detect intent: price, person, location, time-based recall.
   - Extract temporal hints (“today morning”, “around 3 PM”).

21. **Retriever**
   - Combine filters:
     - time window constraints,
     - semantic top-k search,
     - keyword hits (numbers/currency).

22. **Answer composer**
   - Build final response from retrieved evidence.
   - Return:
     - direct answer,
     - confidence,
     - timestamp,
     - “why this answer” evidence snippets.

23. **Uncertainty behavior**
   - If low confidence, say “not certain” and show top candidates.
   - Never fabricate missing values.

24. **Expose API endpoint**
   - `POST /ask` with `{question: ...}`
   - Response includes answer and evidence payload.

---

## Phase F — Demo UX and Storytelling

25. **Build simple web UI**
   - Live status (stream connected, processed fragments count).
   - Chat box for questions.
   - Clickable evidence timeline.

26. **Create demo script with deterministic moments**
   - Record 20–30 minute “day simulation” containing:
     - spoken facts,
     - visible prices on screen/paper,
     - object interactions (bag, notebook, bottle).

27. **Prepare benchmark questions before demo**
   - 10 fixed questions with known ground truth.
   - Measure answer correctness and latency.

28. **Fallback demo mode**
   - Save a known sample stream locally.
   - Switch to offline replay if Wi-Fi/phone stream fails.

---

## 4) Hackathon Timeline (Practical)

### Day 1
- Stream ingestion + fragmentation stable.
- Basic ASR + OCR pipeline running.

### Day 2
- Object detection + event fusion + DB schema.
- First retrieval and `/ask` endpoint.

### Day 3
- Improve answer quality, confidence, and evidence.
- Build minimal UI and run full demo rehearsal.

### Final hours
- Performance tuning (batch sizes, frame sampling).
- Polish presentation + backup video.

---

## 5) Accuracy and Performance Tips

- **Sampling strategy:** 1 FPS keyframes is often enough for hackathon; increase only when needed.
- **OCR quality:** prioritize clear front camera angle and steady mount.
- **Latency target:** keep ingestion real-time; processing can lag by 1–3 minutes.
- **Edge-case handling:** motion blur, low light, noisy audio.

---

## 6) Privacy, Safety, and Ethics (Must-Have)

- Add visible “recording on” indicator in UI.
- Require explicit user consent for any bystander data capture.
- Encrypt stored fragments if possible.
- Provide delete endpoint:
  - delete by time range,
  - delete entire day.
- Avoid face recognition identity claims unless tested/consented.

---

## 7) Concrete Deliverables Checklist

- [ ] Android IP camera stream connected to laptop.
- [ ] Fragment files generated continuously.
- [ ] ML pipeline produces OCR/object/transcript outputs.
- [ ] Memory events stored with timestamps.
- [ ] Semantic + keyword retrieval works.
- [ ] `/ask` returns answer + evidence.
- [ ] Demo UI functional.
- [ ] Fallback offline replay mode ready.
- [ ] 10 benchmark Q&A results recorded.

---

## 8) Example Questions Your System Should Answer

- “What was the price of the flight ticket I looked at?”
- “What shop name did I pass after lunch?”
- “Who was I talking to at around 5 PM?”
- “Where did I put my charger?”
- “What tasks did I mention in the morning?”

---

## 9) Suggested Next Immediate Actions (First 2 Hours)

1. Choose and install Android IP camera app.
2. Confirm stream URL works with `ffplay` on laptop.
3. Implement fragment writer with reconnect.
4. Run one 5-minute capture and verify fragment timestamps.
5. Add OCR + Whisper for one fragment and inspect outputs.

Once these are done, you have the core spine of the project and can iterate quickly.