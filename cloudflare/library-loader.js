/* Cloud-only data loading. The local page keeps its complete embedded library. */
(() => {
  const config = JSON.parse(document.getElementById('cloudLibraryConfig').textContent);
  let notes, callbacks, allPromise, query = '', searchFailed = false;
  let searchTimer, progressTimer;
  const detailStates = new Map(), completed = new Set();
  const status = () => document.getElementById('libraryStatus');
  const ready = () => completed.size === config.chunks.length;

  function showStatus(message, retry) {
    const box = status();
    box.replaceChildren();
    box.hidden = !message;
    if (!message) return;
    const text = document.createElement('span');
    text.textContent = message;
    box.append(text);
    if (retry) {
      const button = document.createElement('button');
      button.textContent = '重新加载';
      button.onclick = retry;
      box.append(button);
    }
  }

  function searchStatus() {
    if (!query || ready()) return showStatus('');
    if (searchFailed) {
      showStatus('部分搜索内容未加载成功，当前结果可能不完整。', () => search(query));
    } else {
      showStatus(`正在补充搜索结果（${completed.size}/${config.chunks.length}），当前结果可能不完整…`);
    }
  }

  async function getJSON(url, prefetch = false) {
    let lastError;
    for (let attempt = 0; attempt < (prefetch ? 1 : 2); attempt++) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), prefetch ? 4000 : 15000);
      try {
        const response = await fetch(url, {
          signal: controller.signal, cache: 'default', priority: prefetch ? 'low' : 'auto',
        });
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return await response.json();
      } catch (error) { lastError = error; }
      finally { clearTimeout(timer); }
    }
    throw lastError;
  }

  function merge(full) {
    const note = notes.find(n => n.id === full.id);
    if (!note || !full.reviewedSummary?.sections ||
        full.reviewedSummary.tldr !== note.reviewedSummary.tldr) {
      throw new Error('报告内容与目录不匹配');
    }
    Object.assign(note, full);
    delete note._s;
    detailStates.set(note.id, {state: 'loaded'});
    return note;
  }

  function progress() {
    if (!query || progressTimer) return;
    progressTimer = setTimeout(() => {
      progressTimer = null;
      if (query) { callbacks.search(); searchStatus(); }
    }, 80);
  }

  async function select(note, prefetch = false) {
    if (!note) return;
    const state = detailStates.get(note.id);
    if (state?.state === 'loaded') return;
    if (state?.state === 'loading') {
      await state.promise;
      if (!prefetch && state.prefetch && detailStates.get(note.id)?.state !== 'loaded') {
        return select(note);
      }
      return;
    }
    const loading = {state: 'loading', prefetch};
    detailStates.set(note.id, loading);
    if (!prefetch) callbacks.detail(note.id);
    loading.promise = (async () => {
      try {
        const full = await getJSON(note.detailFile, prefetch);
        if (full.id !== note.id) throw new Error('报告编号不匹配');
        merge(full);
        progress();
      } catch {
        // A background search may already have supplied this report.
        if (detailStates.get(note.id)?.state !== 'loaded') {
          detailStates.set(note.id, {state: prefetch ? 'idle' : 'error'});
        }
      }
      callbacks.detail(note.id);
    })();
    return loading.promise;
  }

  async function all() {
    if (ready()) return;
    if (allPromise) return allPromise;
    allPromise = (async () => {
      const queue = config.chunks.filter(chunk => !completed.has(chunk.url));
      let failure;
      async function worker() {
        while (queue.length) {
          const chunk = queue.shift();
          try {
            const batch = await getJSON(chunk.url);
            if (!Array.isArray(batch) || batch.length !== chunk.ids.length ||
                batch.some((note, i) => note.id !== chunk.ids[i])) {
              throw new Error('搜索内容不完整');
            }
            batch.forEach(merge);
            completed.add(chunk.url);
            batch.forEach(note => callbacks.detail(note.id));
            progress();
          } catch (error) { failure = error; }
        }
      }
      await Promise.all([worker(), worker(), worker()]);
      if (failure) throw failure;
    })();
    try { await allPromise; } finally { allPromise = null; }
  }

  function search(value) {
    query = value;
    clearTimeout(searchTimer);
    if (!query || ready()) { searchStatus(); return; }
    searchFailed = false;
    searchStatus();
    searchTimer = setTimeout(async () => {
      try { await all(); } catch { searchFailed = true; }
      callbacks.search();
      searchStatus();
    }, 160);
  }

  function canPrefetch() {
    const connection = navigator.connection;
    return document.visibilityState === 'visible' && !query && !allPromise &&
      [...detailStates.values()].filter(state => state.state === 'loading' && state.prefetch).length < 2 &&
      !connection?.saveData && !['slow-2g', '2g', '3g'].includes(connection?.effectiveType);
  }

  function startPrefetch() {
    let hoverTimer;
    document.addEventListener('pointerover', event => {
      const row = event.target.closest('.report-row');
      if (!row || row.contains(event.relatedTarget) || !canPrefetch()) return;
      clearTimeout(hoverTimer);
      hoverTimer = setTimeout(() => {
        if (canPrefetch() && row.matches(':hover')) select(notes.find(n => n.id === row.dataset.id), true);
      }, 120);
    });
    document.addEventListener('pointerout', event => {
      const row = event.target.closest('.report-row');
      if (row && !row.contains(event.relatedTarget)) clearTimeout(hoverTimer);
    });
    setTimeout(async () => {
      const rows = [...document.querySelectorAll('.report-row')].slice(0, 2);
      for (const row of rows) {
        if (!canPrefetch()) break;
        await select(notes.find(n => n.id === row.dataset.id), true);
      }
    }, 1800);
  }

  function startCache() {
    if (!('serviceWorker' in navigator)) return;
    let requestedUpdate = false;
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (requestedUpdate) location.reload();
    });
    navigator.serviceWorker.register('/sw.js', {updateViaCache: 'none'}).then(registration => {
      function offerUpdate() {
        if (!registration.waiting || !navigator.serviceWorker.controller ||
            document.getElementById('cacheUpdate')) return;
        const box = document.createElement('div');
        box.id = 'cacheUpdate';
        box.className = 'library-status';
        box.setAttribute('role', 'status');
        box.append('知识库有新版本。');
        const button = document.createElement('button');
        button.textContent = '立即更新';
        button.onclick = () => {
          if (!registration.waiting) { location.reload(); return; }
          requestedUpdate = true;
          button.disabled = true;
          button.textContent = '正在更新…';
          registration.waiting.postMessage({type: 'ACTIVATE_UPDATE'});
        };
        box.append(button);
        status().before(box);
      }
      offerUpdate();
      registration.addEventListener('updatefound', () => {
        const worker = registration.installing;
        worker?.addEventListener('statechange', () => {
          if (worker.state === 'installed') offerUpdate();
        });
      });
      window.addEventListener('online', () => registration.update().catch(() => {}));
    }).catch(() => {});
  }

  window.StarKnowsLoader = {
    attach(data, handlers) {
      notes = data;
      callbacks = handlers;
      showStatus('');
      startPrefetch();
      setTimeout(startCache, 1200);
    },
    select, search, all,
    detailState: note => detailStates.get(note.id)?.state || 'loading',
  };
})();
