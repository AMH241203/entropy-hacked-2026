const uploadBtn = document.getElementById('uploadBtn');
const uploadStatus = document.getElementById('uploadStatus');
const searchBtn = document.getElementById('searchBtn');
const queryInput = document.getElementById('queryInput');
const resultsDiv = document.getElementById('results');
const player = document.getElementById('player');
const currentClip = document.getElementById('currentClip');

uploadBtn.addEventListener('click', async () => {
  const fileEl = document.getElementById('videoFile');
  const file = fileEl.files[0];
  if (!file) {
    uploadStatus.textContent = 'Please choose a video file.';
    return;
  }

  uploadStatus.textContent = 'Uploading and processing...';
  const form = new FormData();
  form.append('file', file);

  const res = await fetch('/upload', { method: 'POST', body: form });
  const data = await res.json();
  if (!res.ok) {
    uploadStatus.textContent = `Error: ${data.detail || 'Upload failed'}`;
    return;
  }

  uploadStatus.textContent = `Ready. Video ID: ${data.video_id}, chunks: ${data.chunks}`;
});

searchBtn.addEventListener('click', async () => {
  const q = queryInput.value.trim();
  if (!q) return;

  resultsDiv.innerHTML = 'Searching...';
  const res = await fetch(`/search?q=${encodeURIComponent(q)}`);
  const data = await res.json();

  if (!res.ok) {
    resultsDiv.textContent = data.detail || 'Search failed';
    return;
  }

  renderResults(data.results || []);
});

function renderResults(results) {
  if (!results.length) {
    resultsDiv.innerHTML = '<p>No matches yet. Upload a video first.</p>';
    return;
  }

  resultsDiv.innerHTML = '';
  for (const item of results) {
    const row = document.createElement('div');
    row.className = 'item';
    row.innerHTML = `
      <div><strong>${item.filename}</strong> (chunk #${item.chunk_idx})</div>
      <div class="meta">${item.start_s.toFixed(1)}s - ${item.end_s.toFixed(1)}s | score: ${item.score}</div>
      <div>${item.snippet}</div>
      <button>Play this clip</button>
    `;

    row.querySelector('button').addEventListener('click', () => {
      player.src = item.clip_url;
      player.play();
      currentClip.textContent = `Playing ${item.filename} [${item.start_s.toFixed(1)}s - ${item.end_s.toFixed(1)}s]`;
    });

    resultsDiv.appendChild(row);
  }
}