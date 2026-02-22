const uploadBtn = document.getElementById('uploadBtn');
const uploadStatus = document.getElementById('uploadStatus');
const searchBtn = document.getElementById('searchBtn');
const queryInput = document.getElementById('queryInput');
const resultsDiv = document.getElementById('results');
const player = document.getElementById('player');
const currentClip = document.getElementById('currentClip');
const fileInput = document.getElementById('videoFile');


fileInput.addEventListener('change', () => {
    if (!fileInput.files[0]) {
      uploadStatus.textContent = '';
      return;
    }
    const file = fileInput.files[0];
    uploadStatus.textContent = `Selected: ${file.name}`;
  });
  
  uploadBtn.addEventListener('click', async (event) => {
    event.preventDefault();
    const file = fileInput.files[0];
    if (!file) {
        uploadStatus.textContent = 'Please choose a video file first.';
    return;
  }

  uploadStatus.textContent = 'Uploading and indexing chunks...';
  uploadBtn.disabled = true;

  try {
    const form = new FormData();
    form.append('file', file);

    const res = await fetch('/upload', { method: 'POST', body: form });
    const data = await res.json();

    if (!res.ok) {
      uploadStatus.textContent = `Error: ${data.detail || 'Upload failed'}`;
      return;
    }

    uploadStatus.textContent = `Ready ✓ Video ID: ${data.video_id} • ${data.chunks} chunks indexed`;
  } catch (error) {
    uploadStatus.textContent = `Error: ${error.message}`;
  } finally {
    uploadBtn.disabled = false;
  }
});

searchBtn.addEventListener('click', runSearch);
queryInput.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') runSearch();
});

async function runSearch() {
  const q = queryInput.value.trim();
  if (!q) {
    resultsDiv.innerHTML = '<p class="meta">Type a query first.</p>';
    return;
  }

  resultsDiv.innerHTML = '<p class="meta">Searching...</p>';
  try {
    const res = await fetch(`/search?q=${encodeURIComponent(q)}`);
    const data = await res.json();

    if (!res.ok) {
      resultsDiv.textContent = data.detail || 'Search failed';
      return;
    }

    renderResults(data.results || []);
  } catch (error) {
    resultsDiv.textContent = `Search failed: ${error.message}`;
  }
}

function renderResults(results) {
  if (!results.length) {
    resultsDiv.innerHTML = '<p class="meta">No results yet. Upload and index a video first.</p>';
    return;
  }

  resultsDiv.innerHTML = '';
  for (const item of results) {
    const row = document.createElement('div');
    row.className = 'item';
    row.innerHTML = `
      <div><strong>${item.filename}</strong> (chunk #${item.chunk_idx})</div>
      <div class="meta">${item.start_s.toFixed(1)}s - ${item.end_s.toFixed(1)}s • score: ${item.score}</div>
      <div>${item.snippet || 'No snippet available.'}</div>
      <button class="result-play" type="button">Play this clip</button>
    `;

    row.querySelector('button').addEventListener('click', async () => {
      player.src = item.clip_url;
      currentClip.textContent = `Playing ${item.filename} [${item.start_s.toFixed(1)}s - ${item.end_s.toFixed(1)}s]`;
      try {
        await player.play();
      } catch (_) {
        // autoplay may be blocked by browser; controls still allow manual play.
      }


    });

    resultsDiv.appendChild(row);
  }
}