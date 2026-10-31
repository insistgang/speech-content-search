(() => {
  'use strict';

  const byId = (id) => document.getElementById(id);
  const connectionState = byId('connection-state');
  const connectionLabel = byId('connection-label');
  const globalMessage = byId('global-message');
  const videoTableBody = byId('video-table-body');
  const taskTableBody = byId('task-table-body');
  const keywordSetList = byId('keyword-set-list');
  const searchResults = byId('search-results');
  const playerPanel = byId('player-panel');
  const videoPlayer = byId('video-player');

  let currentVideos = [];
  let currentTasks = [];
  let currentKeywordSets = [];
  let pollTimer = null;
  let pollRequested = false;
  let pollEmptyChecks = 0;
  let pollErrors = 0;
  let playbackToken = 0;
  let refreshFailureVisible = false;

  const STATUS_LABELS = Object.freeze({
    pending: '等待中',
    processing: '处理中',
    running: '运行中',
    completed: '已完成',
    ready: '可检索',
    failed: '失败',
  });

  const STATUS_CLASSES = Object.freeze({
    completed: 'status-completed',
    ready: 'status-ready',
    running: 'status-running',
    processing: 'status-processing',
    failed: 'status-failed',
  });

  function setMessage(element, message, kind = '') {
    if (!element) return;
    element.textContent = message || '';
    element.classList.remove('is-error', 'is-success');
    if (kind === 'error') element.classList.add('is-error');
    if (kind === 'success') element.classList.add('is-success');
  }

  function setGlobalMessage(message, kind = 'info') {
    globalMessage.textContent = message || '';
    globalMessage.className = `notice notice-${kind}`;
  }

  function setConnection(online, message) {
    connectionLabel.textContent = message;
    connectionState.classList.toggle('is-online', online);
    connectionState.classList.toggle('is-offline', !online);
  }

  function errorText(error) {
    return error instanceof Error ? error.message : String(error || '未知错误');
  }

  function isFiniteValue(value) {
    return value !== null
      && value !== undefined
      && value !== ''
      && Number.isFinite(Number(value));
  }

  function payloadError(data, fallback) {
    if (data && typeof data.detail === 'string' && data.detail.trim()) return data.detail;
    if (data && typeof data.message === 'string' && data.message.trim()) return data.message;
    if (data && data.detail && typeof data.detail === 'object') {
      try {
        return JSON.stringify(data.detail);
      } catch {
        return fallback;
      }
    }
    return fallback;
  }

  async function requestJson(path, options = {}) {
    const headers = {
      Accept: 'application/json',
      ...(options.headers || {}),
    };
    const response = await fetch(path, { ...options, headers });
    let data = null;
    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      try {
        data = await response.json();
      } catch {
        data = null;
      }
    } else {
      const bodyText = await response.text();
      if (bodyText) data = { detail: bodyText };
    }
    if (!response.ok) {
      throw new Error(payloadError(data, `请求失败（${response.status}）`));
    }
    return data;
  }

  function jsonOptions(method, body) {
    return {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    };
  }

  function makeCell(row, label, text, className = '') {
    const cell = document.createElement('td');
    cell.dataset.label = label;
    if (className) cell.className = className;
    cell.textContent = text === null || text === undefined || text === '' ? '—' : String(text);
    row.append(cell);
    return cell;
  }

  function makeActionButton(label, action, id, style = 'button-quiet') {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `button button-small ${style}`;
    button.textContent = label;
    button.dataset.action = action;
    button.dataset.id = String(id);
    return button;
  }

  function makeStatusBadge(value) {
    const badge = document.createElement('span');
    const status = String(value || '');
    badge.className = `status-badge ${STATUS_CLASSES[status] || ''}`.trim();
    badge.textContent = STATUS_LABELS[status] || (status ? `状态：${status}` : '未知');
    return badge;
  }

  function formatDuration(seconds) {
    if (!isFiniteValue(seconds)) return '—';
    const value = Number(seconds);
    if (!Number.isFinite(value) || value < 0) return '—';
    const total = Math.floor(value);
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const remainder = total % 60;
    if (hours > 0) {
      return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`;
    }
    return `${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`;
  }

  function formatTimestamp(milliseconds) {
    const value = Number(milliseconds);
    if (!Number.isFinite(value) || value < 0) return '';
    const wholeSeconds = Math.floor(value / 1000);
    const hours = Math.floor(wholeSeconds / 3600);
    const minutes = Math.floor((wholeSeconds % 3600) / 60);
    const seconds = wholeSeconds % 60;
    const millis = Math.floor(value % 1000);
    const base = hours > 0
      ? `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
      : `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    return `${base}.${String(millis).padStart(3, '0')}`;
  }

  function formatDate(value) {
    if (!value) return '—';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false });
  }

  function isActiveTask(task) {
    return task && (task.status === 'pending' || task.status === 'running');
  }

  function videoNameById(videoId) {
    const video = currentVideos.find((item) => String(item.id) === String(videoId));
    return video ? video.file_name : `视频 ${videoId}`;
  }

  function renderVideos(videos) {
    currentVideos = Array.isArray(videos) ? videos : [];
    videoTableBody.replaceChildren();
    byId('videos-empty').hidden = currentVideos.length > 0;

    for (const video of currentVideos) {
      const row = document.createElement('tr');
      const nameCell = document.createElement('td');
      nameCell.dataset.label = '视频';
      const name = document.createElement('span');
      name.className = 'video-name';
      name.textContent = video.file_name || '未命名视频';
      const path = document.createElement('span');
      path.className = 'video-path';
      path.textContent = video.path || '';
      nameCell.append(name, path);
      row.append(nameCell);

      makeCell(row, '时长', formatDuration(video.duration_seconds));
      const statusCell = document.createElement('td');
      statusCell.dataset.label = '状态';
      statusCell.append(makeStatusBadge(video.status));
      row.append(statusCell);
      const errorCell = makeCell(row, '错误信息', video.error_message || '');
      if (video.error_message) errorCell.classList.add('error-text');

      const actionCell = document.createElement('td');
      actionCell.dataset.label = '操作';
      const actions = document.createElement('div');
      actions.className = 'row-actions';
      if (video.status === 'failed') {
        const retryButton = makeActionButton('重试转写', 'retry-video', video.id, 'button-secondary');
        retryButton.setAttribute('aria-label', `重试 ${video.file_name || '此视频'} 的转写`);
        actions.append(retryButton);
      }
      const deleteButton = makeActionButton('删除索引', 'delete-video', video.id, 'button-danger');
      deleteButton.setAttribute('aria-label', `删除 ${video.file_name || '此视频'} 的索引记录`);
      actions.append(deleteButton);
      actionCell.append(actions);
      row.append(actionCell);
      videoTableBody.append(row);
    }
  }

  function renderTasks(tasks) {
    currentTasks = Array.isArray(tasks) ? tasks : [];
    taskTableBody.replaceChildren();
    byId('tasks-empty').hidden = currentTasks.length > 0;

    for (const task of currentTasks) {
      const row = document.createElement('tr');
      makeCell(row, '任务', task.id);
      makeCell(row, '视频', videoNameById(task.video_id));
      const statusCell = document.createElement('td');
      statusCell.dataset.label = '状态';
      statusCell.append(makeStatusBadge(task.status));
      row.append(statusCell);

      const rawProgress = isFiniteValue(task.progress) ? Number(task.progress) : null;
      const progress = rawProgress === null ? null : Math.min(100, Math.max(0, rawProgress));
      const progressCell = document.createElement('td');
      progressCell.dataset.label = '进度';
      progressCell.className = 'progress-cell';
      const progressLabel = document.createElement('span');
      progressLabel.textContent = progress === null ? '—' : `${Math.round(progress)}%`;
      progressCell.append(progressLabel);
      if (progress !== null) {
        const track = document.createElement('span');
        track.className = 'progress-track';
        track.setAttribute('aria-hidden', 'true');
        const fill = document.createElement('span');
        fill.className = 'progress-fill';
        fill.style.width = `${progress}%`;
        track.append(fill);
        progressCell.append(track);
      }
      row.append(progressCell);

      makeCell(row, '更新时间', formatDate(task.updated_at || task.created_at));
      const errorCell = makeCell(row, '错误信息', task.error_message || '');
      if (task.error_message) errorCell.classList.add('error-text');
      taskTableBody.append(row);
    }
  }

  function renderKeywordSets(sets) {
    currentKeywordSets = Array.isArray(sets) ? sets : [];
    const select = byId('search-keyword-set');
    const selectedValue = select.value;
    const defaultOption = document.createElement('option');
    defaultOption.value = '';
    defaultOption.textContent = '不限定词库';
    select.replaceChildren(defaultOption);
    keywordSetList.replaceChildren();
    byId('keywords-empty').hidden = currentKeywordSets.length > 0;

    for (const set of currentKeywordSets) {
      const option = document.createElement('option');
      option.value = String(set.id);
      option.textContent = set.name || `词库 ${set.id}`;
      select.append(option);

      const card = document.createElement('article');
      card.className = 'keyword-set-card';
      const main = document.createElement('div');
      main.className = 'keyword-set-main';
      const title = document.createElement('h3');
      title.className = 'keyword-set-name';
      title.textContent = set.name || `词库 ${set.id}`;
      const termList = document.createElement('ul');
      termList.className = 'keyword-terms-list';
      for (const term of Array.isArray(set.terms) ? set.terms : []) {
        const termItem = document.createElement('li');
        termItem.className = 'keyword-term';
        termItem.textContent = String(term);
        termList.append(termItem);
      }
      main.append(title, termList);
      card.append(main, makeActionButton('删除词库', 'delete-keyword-set', set.id, 'button-danger'));
      keywordSetList.append(card);
    }

    if (currentKeywordSets.some((set) => String(set.id) === selectedValue)) {
      select.value = selectedValue;
    }
  }

  function renderSearchResults(data) {
    const results = Array.isArray(data && data.results) ? data.results : [];
    searchResults.replaceChildren();
    const empty = byId('results-empty');
    empty.hidden = results.length > 0;
    if (results.length === 0) {
      empty.textContent = '没有找到符合条件的转写片段。';
      return;
    }

    for (const result of results) {
      const card = document.createElement('article');
      card.className = 'result-card';
      const header = document.createElement('div');
      header.className = 'result-card-header';
      const identity = document.createElement('div');
      identity.className = 'result-file';
      identity.textContent = result.file_name || `视频 ${result.video_id}`;
      const meta = document.createElement('div');
      meta.className = 'result-meta';
      const mode = document.createElement('span');
      mode.textContent = result.match_type === 'exact' ? '精确匹配' : result.match_type === 'fuzzy' ? '模糊匹配' : '检索结果';
      meta.append(mode);
      if (isFiniteValue(result.score)) {
        const score = document.createElement('span');
        score.textContent = `得分 ${Number(result.score).toFixed(2)}`;
        meta.append(score);
      }
      header.append(identity, meta);

      const segment = document.createElement('p');
      segment.className = 'result-text';
      segment.textContent = result.text === null || result.text === undefined ? '' : String(result.text);

      const footer = document.createElement('div');
      footer.className = 'result-card-footer';
      const timestamp = document.createElement('span');
      timestamp.className = 'timestamp-label';
      const hasTimestamp = result.timestamp_available === true
        && isFiniteValue(result.start_ms)
        && Number(result.start_ms) >= 0;
      let startMs = null;
      if (hasTimestamp) {
        startMs = Number(result.start_ms);
        const start = formatTimestamp(startMs);
        const end = isFiniteValue(result.end_ms) && Number(result.end_ms) >= startMs
          ? formatTimestamp(Number(result.end_ms))
          : '';
        timestamp.textContent = end ? `时间 ${start}–${end}` : `时间 ${start}`;
      } else {
        timestamp.textContent = '无时间戳';
      }

      const playButton = document.createElement('button');
      playButton.type = 'button';
      playButton.className = 'button button-small button-secondary';
      playButton.textContent = hasTimestamp ? '定位播放' : '从头播放';
      playButton.addEventListener('click', () => {
        openVideo(result.video_id, result.file_name, startMs);
      });
      footer.append(timestamp, playButton);
      card.append(header, segment, footer);
      searchResults.append(card);
    }
  }

  function openVideo(videoId, fileName, startMs) {
    if (videoId === null || videoId === undefined || String(videoId) === '') {
      setMessage(byId('search-message'), '该检索结果缺少视频编号，无法打开视频。', 'error');
      return;
    }
    const token = ++playbackToken;
    playerPanel.hidden = false;
    byId('player-title').textContent = fileName || `视频 ${videoId}`;
    byId('player-note').textContent = startMs === null
      ? '该片段无时间戳，视频从头播放。'
      : `正在定位到 ${formatTimestamp(startMs)}。`;
    videoPlayer.pause();
    videoPlayer.src = `/api/videos/${encodeURIComponent(String(videoId))}/file`;
    videoPlayer.load();
    playerPanel.scrollIntoView({ behavior: 'smooth', block: 'center' });

    let metadataHandled = false;
    const onMetadata = () => {
      if (token !== playbackToken || metadataHandled) return;
      metadataHandled = true;
      if (startMs !== null) {
        const seconds = Number(startMs) / 1000;
        if (Number.isFinite(videoPlayer.duration) && seconds > videoPlayer.duration) {
          byId('player-note').textContent = '转写时间戳超出视频时长，未执行定位。';
          return;
        }
        videoPlayer.currentTime = seconds;
      }
      const playPromise = videoPlayer.play();
      if (playPromise && typeof playPromise.catch === 'function') {
        playPromise.catch(() => {
          if (token === playbackToken) byId('player-note').textContent += ' 请使用播放器控件开始播放。';
        });
      }
    };
    const onPlayerError = () => {
      if (token === playbackToken) byId('player-note').textContent = '无法读取该视频文件；请确认索引记录和本地文件仍可用。';
    };
    videoPlayer.addEventListener('loadedmetadata', onMetadata, { once: true });
    videoPlayer.addEventListener('error', onPlayerError, { once: true });
    if (videoPlayer.readyState >= 1) onMetadata();
  }

  function scheduleTaskPoll(delay = 1200) {
    if (pollTimer || !pollRequested) return;
    pollTimer = window.setTimeout(async () => {
      pollTimer = null;
      await refreshLists({ quiet: true });
    }, delay);
  }

  function continueTaskPolling() {
    const hasActiveTask = currentTasks.some(isActiveTask);
    if (hasActiveTask) {
      pollRequested = true;
      pollEmptyChecks = 0;
      pollErrors = 0;
      scheduleTaskPoll();
      return;
    }
    if (pollRequested && pollEmptyChecks < 2) {
      pollEmptyChecks += 1;
      scheduleTaskPoll();
      return;
    }
    pollRequested = false;
    pollEmptyChecks = 0;
  }

  function beginTaskPolling() {
    pollRequested = true;
    pollEmptyChecks = 0;
    pollErrors = 0;
    scheduleTaskPoll(300);
  }

  async function refreshLists({ quiet = false } = {}) {
    try {
      const [taskData, videoData] = await Promise.all([
        requestJson('/api/tasks'),
        requestJson('/api/videos'),
      ]);
      if (!taskData || !Array.isArray(taskData.tasks) || !videoData || !Array.isArray(videoData.videos)) {
        throw new Error('本地服务返回的任务或视频列表格式不正确。');
      }
      renderVideos(videoData.videos);
      renderTasks(taskData.tasks);
      if (!quiet || refreshFailureVisible) {
        setGlobalMessage(refreshFailureVisible ? '视频和任务列表连接已恢复。' : '视频和任务列表已更新。', 'success');
        refreshFailureVisible = false;
      }
      continueTaskPolling();
      return true;
    } catch (error) {
      setGlobalMessage(`读取列表失败：${errorText(error)}`, 'error');
      refreshFailureVisible = true;
      if (pollRequested) {
        pollErrors += 1;
        if (pollErrors <= 5) scheduleTaskPoll(2500);
        else pollRequested = false;
      }
      return false;
    }
  }

  async function refreshKeywords() {
    const data = await requestJson('/api/keywords');
    if (!data || !Array.isArray(data.sets)) throw new Error('本地服务返回的词库格式不正确。');
    renderKeywordSets(data.sets);
  }

  function currentProvider() {
    return byId('provider-select').value === 'whisper' ? 'whisper' : 'sidecar';
  }

  async function handleFileImport(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector('button[type="submit"]');
    const path = byId('file-path').value.trim();
    if (!path) {
      setMessage(byId('import-message'), '请填写视频文件路径。', 'error');
      return;
    }
    button.disabled = true;
    setMessage(byId('import-message'), '正在提交导入任务…');
    try {
      const data = await requestJson('/api/videos/import-file', jsonOptions('POST', {
        path,
        provider: currentProvider(),
      }));
      const duplicate = data && data.duplicate === true;
      setMessage(
        byId('import-message'),
        duplicate ? '该视频已在索引中，已刷新当前状态。' : '导入已提交；任务状态会自动刷新。',
        'success',
      );
      await refreshLists({ quiet: true });
      if (!duplicate || data.task) beginTaskPolling();
    } catch (error) {
      setMessage(byId('import-message'), `导入失败：${errorText(error)}`, 'error');
    } finally {
      button.disabled = false;
    }
  }

  function describeFolderError(item) {
    if (typeof item === 'string') return item;
    if (!item || typeof item !== 'object') return String(item);
    const name = item.path || item.file || '';
    const reason = item.error || item.message || item.detail || '';
    return [name, typeof reason === 'string' ? reason : JSON.stringify(reason)].filter(Boolean).join('：') || JSON.stringify(item);
  }

  async function handleFolderImport(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector('button[type="submit"]');
    const path = byId('folder-path').value.trim();
    if (!path) {
      setMessage(byId('import-message'), '请填写文件夹路径。', 'error');
      return;
    }
    button.disabled = true;
    setMessage(byId('import-message'), '正在扫描文件夹…');
    try {
      const data = await requestJson('/api/videos/import-folder', jsonOptions('POST', {
        path,
        provider: currentProvider(),
        recursive: byId('recursive').checked,
      }));
      const imported = Array.isArray(data && data.imported) ? data.imported.length : 0;
      const errors = Array.isArray(data && data.errors) ? data.errors : [];
      const summary = `文件夹扫描完成：提交 ${imported} 个视频，${errors.length} 个项目失败。`;
      setMessage(byId('import-message'), errors.length ? `${summary} ${errors.map(describeFolderError).join('；')}` : summary, errors.length ? 'error' : 'success');
      await refreshLists({ quiet: true });
      if (imported > 0) beginTaskPolling();
    } catch (error) {
      setMessage(byId('import-message'), `扫描失败：${errorText(error)}`, 'error');
    } finally {
      button.disabled = false;
    }
  }

  async function retryVideo(videoId, button) {
    const provider = currentProvider();
    button.disabled = true;
    setGlobalMessage(`正在重试视频 ${videoId}…`, 'info');
    try {
      const data = await requestJson(`/api/videos/${encodeURIComponent(videoId)}/retry`, jsonOptions('POST', { provider }));
      setGlobalMessage('重试任务已提交；任务状态会自动刷新。', 'success');
      await refreshLists({ quiet: true });
      if (data && data.task) beginTaskPolling();
    } catch (error) {
      setGlobalMessage(`重试失败：${errorText(error)}`, 'error');
    } finally {
      button.disabled = false;
    }
  }

  async function deleteVideo(videoId, button) {
    const video = currentVideos.find((item) => String(item.id) === String(videoId));
    const name = video ? video.file_name : `视频 ${videoId}`;
    if (!window.confirm(`删除“${name}”的本地索引记录和系统生成的音频缓存？原视频文件不会被删除。`)) return;
    button.disabled = true;
    try {
      await requestJson(`/api/videos/${encodeURIComponent(videoId)}`, { method: 'DELETE' });
      setGlobalMessage('视频索引记录及系统生成的音频缓存已删除；源视频未删除。', 'success');
      await refreshLists({ quiet: true });
    } catch (error) {
      setGlobalMessage(`删除失败：${errorText(error)}`, 'error');
    } finally {
      button.disabled = false;
    }
  }

  async function handleVideoAction(event) {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const id = button.dataset.id;
    if (button.dataset.action === 'retry-video') await retryVideo(id, button);
    if (button.dataset.action === 'delete-video') await deleteVideo(id, button);
  }

  async function handleSearch(event) {
    event.preventDefault();
    const query = byId('search-query').value.trim();
    const selectedId = byId('search-keyword-set').value;
    if (!query && !selectedId) {
      searchResults.replaceChildren();
      byId('results-empty').hidden = false;
      byId('results-empty').textContent = '请输入检索词，或先选择一个词库。';
      setMessage(byId('search-message'), '请输入检索词或选择词库。', 'error');
      return;
    }

    const keywordSetId = selectedId === '' ? null : selectedId;
    const button = event.currentTarget.querySelector('button[type="submit"]');
    button.disabled = true;
    searchResults.replaceChildren();
    byId('results-empty').hidden = true;
    setMessage(byId('search-message'), '正在检索本地转写文本…');
    try {
      const data = await requestJson('/api/search', jsonOptions('POST', {
        query,
        mode: byId('search-mode').value === 'fuzzy' ? 'fuzzy' : 'exact',
        limit: 30,
        keyword_set_id: keywordSetId,
      }));
      renderSearchResults(data);
      const count = Number(data && data.count);
      setMessage(byId('search-message'), Number.isFinite(count) ? `检索完成，共找到 ${count} 条结果。` : '检索完成。', 'success');
    } catch (error) {
      searchResults.replaceChildren();
      byId('results-empty').hidden = false;
      byId('results-empty').textContent = '检索未完成，请检查输入或查看错误信息。';
      setMessage(byId('search-message'), `检索失败：${errorText(error)}`, 'error');
    } finally {
      button.disabled = false;
    }
  }

  async function handleKeywordCreate(event) {
    event.preventDefault();
    const name = byId('keyword-name').value.trim();
    const terms = byId('keyword-terms').value.split(/\r?\n/).map((term) => term.trim()).filter(Boolean);
    if (!name || terms.length === 0) {
      setMessage(byId('keyword-message'), '请填写词库名称和至少一个词条。', 'error');
      return;
    }
    const button = event.currentTarget.querySelector('button[type="submit"]');
    button.disabled = true;
    setMessage(byId('keyword-message'), '正在创建词库…');
    try {
      await requestJson('/api/keywords', jsonOptions('POST', { name, terms }));
      byId('keyword-terms').value = '';
      await refreshKeywords();
      setMessage(byId('keyword-message'), '词库已创建。', 'success');
    } catch (error) {
      setMessage(byId('keyword-message'), `创建失败：${errorText(error)}`, 'error');
    } finally {
      button.disabled = false;
    }
  }

  async function deleteKeywordSet(id, button) {
    const set = currentKeywordSets.find((item) => String(item.id) === String(id));
    const name = set ? set.name : `词库 ${id}`;
    if (!window.confirm(`删除词库“${name}”？`)) return;
    button.disabled = true;
    try {
      await requestJson(`/api/keywords/${encodeURIComponent(id)}`, { method: 'DELETE' });
      await refreshKeywords();
      setMessage(byId('keyword-message'), '词库已删除。', 'success');
    } catch (error) {
      setMessage(byId('keyword-message'), `删除失败：${errorText(error)}`, 'error');
    } finally {
      button.disabled = false;
    }
  }

  async function handleKeywordAction(event) {
    const button = event.target.closest('button[data-action="delete-keyword-set"]');
    if (button) await deleteKeywordSet(button.dataset.id, button);
  }

  async function initialize() {
    try {
      const health = await requestJson('/api/health');
      if (!health || health.status !== 'ok') throw new Error('本地服务健康检查未通过。');
      setConnection(true, `本地服务已连接 · ${health.version || '可用'}`);
      setGlobalMessage('正在读取本机视频索引、任务和词库…', 'info');
      const results = await Promise.allSettled([refreshLists(), refreshKeywords()]);
      const failed = results.find((result) => result.status === 'rejected');
      if (failed) throw failed.reason;
      if (!results[0].value) throw new Error('视频或任务列表未能读取。');
      if (currentTasks.some(isActiveTask)) beginTaskPolling();
      else setGlobalMessage('本地索引已就绪。', 'success');
    } catch (error) {
      setConnection(false, '本地服务未连接');
      setGlobalMessage(`无法连接或读取本地服务：${errorText(error)}。请确认服务已在本机启动。`, 'error');
    }
  }

  byId('import-file-form').addEventListener('submit', handleFileImport);
  byId('import-folder-form').addEventListener('submit', handleFolderImport);
  byId('video-table-body').addEventListener('click', handleVideoAction);
  byId('search-form').addEventListener('submit', handleSearch);
  byId('keyword-form').addEventListener('submit', handleKeywordCreate);
  byId('keyword-set-list').addEventListener('click', handleKeywordAction);
  byId('refresh-button').addEventListener('click', () => refreshLists());

  initialize();
})();
