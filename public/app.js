document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const analyzeForm = document.getElementById('analyzeForm');
    const urlInput = document.getElementById('urlInput');
    const pasteBtn = document.getElementById('pasteBtn');
    const analyzeBtn = document.getElementById('analyzeBtn');
    const analyzeSpinner = document.getElementById('analyzeSpinner');
    const resultCard = document.getElementById('resultCard');

    const outputPathInput = document.getElementById('outputPathInput');
    const resetPathBtn = document.getElementById('resetPathBtn');
    const browseFolderBtn = document.getElementById('browseFolderBtn');
    const DEFAULT_PATH = "/Users/chillsyeah/.gemini/antigravity/scratch/downloads";

    const folderPickerInput = document.getElementById('folderPickerInput');

    // Browse Folder button handler (Native HTML5 picker with backend AppleScript fallback)
    browseFolderBtn.addEventListener('click', async () => {
        // First try server API call (native macOS dialog)
        try {
            const res = await fetch('/api/select-folder', { method: 'POST' });
            const data = await res.json();
            if (data.folder_path) {
                outputPathInput.value = data.folder_path;
                showToast(`Selected save folder: ${data.folder_path}`);
                return;
            }
        } catch (e) {
            // fallback to web picker
        }

        // Fallback: trigger HTML directory selector
        folderPickerInput.click();
    });

    folderPickerInput.addEventListener('change', (e) => {
        if (e.target.files && e.target.files.length > 0) {
            const file = e.target.files[0];
            // webkitRelativePath gives "FolderName/file.mp4"
            const relPath = file.webkitRelativePath || '';
            const folderName = relPath.split('/')[0] || '';
            if (folderName) {
                const currentPath = outputPathInput.value.trim();
                const basePath = currentPath.substring(0, currentPath.lastIndexOf('/'));
                const newPath = basePath ? `${basePath}/${folderName}` : `/Users/chillsyeah/Downloads/${folderName}`;
                outputPathInput.value = newPath;
                showToast(`Selected folder: ${newPath}`);
            }
        }
    });

    const videoThumbnail = document.getElementById('videoThumbnail');
    const videoDuration = document.getElementById('videoDuration');
    const videoExtractor = document.getElementById('videoExtractor');
    const playlistBadge = document.getElementById('playlistBadge');
    const videoViews = document.getElementById('videoViews');
    const videoTitle = document.getElementById('videoTitle');
    const videoUploader = document.getElementById('videoUploader');
    const formatSelect = document.getElementById('formatSelect');
    const downloadNowBtn = document.getElementById('downloadNowBtn');

    const playlistContainer = document.getElementById('playlistContainer');
    const playlistItemCount = document.getElementById('playlistItemCount');
    const playlistItemsList = document.getElementById('playlistItemsList');

    const downloadsList = document.getElementById('downloadsList');
    const emptyDownloads = document.getElementById('emptyDownloads');
    const activeCount = document.getElementById('activeCount');

    const historyList = document.getElementById('historyList');
    const emptyHistory = document.getElementById('emptyHistory');
    const clearHistoryBtn = document.getElementById('clearHistoryBtn');
    const openFolderBtn = document.getElementById('openFolderBtn');

    const toast = document.getElementById('toast');
    const toastMsg = document.getElementById('toastMsg');

    let currentVideoData = null;
    let pollInterval = null;

    // Reset path button
    resetPathBtn.addEventListener('click', () => {
        outputPathInput.value = DEFAULT_PATH;
        showToast("Reset to default downloads folder");
    });

    // Toast helper
    function showToast(message, duration = 3000) {
        toastMsg.textContent = message;
        toast.classList.remove('hidden');
        setTimeout(() => {
            toast.classList.add('hidden');
        }, duration);
    }

    // Paste button helper
    pasteBtn.addEventListener('click', async () => {
        try {
            const text = await navigator.clipboard.readText();
            if (text) {
                urlInput.value = text;
                showToast("URL pasted from clipboard!");
            }
        } catch (err) {
            showToast("Unable to read clipboard. Please paste manually.");
        }
    });

    // Open Downloads Folder
    openFolderBtn.addEventListener('click', async () => {
        const customPath = outputPathInput.value.trim() || DEFAULT_PATH;
        try {
            await fetch('/api/open-folder', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filepath: customPath })
            });
            showToast(`Opened folder: ${customPath}`);
        } catch (e) {
            showToast("Failed to open folder");
        }
    });

    // Clear History
    clearHistoryBtn.addEventListener('click', async () => {
        try {
            await fetch('/api/clear-history', { method: 'POST' });
            fetchHistory();
            showToast("History cleared");
        } catch (e) {
            showToast("Failed to clear history");
        }
    });

    // Analyze URL Form Submit
    analyzeForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const url = urlInput.value.trim();
        if (!url) return;

        // UI Loading state
        analyzeBtn.disabled = true;
        analyzeSpinner.classList.remove('hidden');
        resultCard.classList.add('hidden');

        try {
            const res = await fetch(`/api/info?url=${encodeURIComponent(url)}`);
            const data = await res.json();

            if (data.error) {
                showToast(`Error: ${data.error}`);
                return;
            }

            currentVideoData = data;
            renderVideoDetails(data);
            showToast(data.is_playlist ? "Playlist analyzed!" : "Video analyzed!");

        } catch (err) {
            showToast("Failed to analyze URL. Please check server.");
        } finally {
            analyzeBtn.disabled = false;
            analyzeSpinner.classList.add('hidden');
        }
    });

    const selectAllPlaylistBtn = document.getElementById('selectAllPlaylistBtn');
    const deselectAllPlaylistBtn = document.getElementById('deselectAllPlaylistBtn');

    if (selectAllPlaylistBtn) {
        selectAllPlaylistBtn.addEventListener('click', () => {
            document.querySelectorAll('.playlist-checkbox').forEach(cb => cb.checked = true);
            updatePlaylistDownloadBtnText();
        });
    }

    if (deselectAllPlaylistBtn) {
        deselectAllPlaylistBtn.addEventListener('click', () => {
            document.querySelectorAll('.playlist-checkbox').forEach(cb => cb.checked = false);
            updatePlaylistDownloadBtnText();
        });
    }

    function updatePlaylistDownloadBtnText() {
        if (!currentVideoData || !currentVideoData.is_playlist) return;
        const selectedCount = document.querySelectorAll('.playlist-checkbox:checked').length;
        const total = currentVideoData.entry_count || (currentVideoData.entries ? currentVideoData.entries.length : 0);
        downloadNowBtn.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
            Download Selected (${selectedCount} of ${total} Videos)
        `;
    }

    // Render Video / Playlist Info & Format Options
    function renderVideoDetails(data) {
        videoExtractor.textContent = data.extractor || 'Web';
        videoTitle.textContent = data.title || 'Untitled';
        videoUploader.textContent = data.uploader || 'Unknown Channel';

        if (data.is_playlist) {
            playlistBadge.classList.remove('hidden');
            videoDuration.textContent = `${data.entry_count} Videos`;
            videoThumbnail.src = (data.entries && data.entries[0] && data.entries[0].thumbnail) ? data.entries[0].thumbnail : 'https://via.placeholder.com/280x170?text=Playlist';
            
            // Populate playlist items preview list
            playlistContainer.classList.remove('hidden');
            playlistItemCount.textContent = data.entry_count;
            playlistItemsList.innerHTML = '';

            if (data.entries) {
                data.entries.forEach((item, idx) => {
                    const card = document.createElement('div');
                    card.className = 'playlist-item-card';
                    card.innerHTML = `
                        <input type="checkbox" class="playlist-checkbox" data-url="${escapeHtml(item.url)}" data-title="${escapeHtml(item.title)}" data-thumb="${escapeHtml(item.thumbnail || '')}" checked style="accent-color: #8b5cf6; width: 16px; height: 16px; cursor: pointer;">
                        <img src="${item.thumbnail || 'https://via.placeholder.com/50x35'}" alt="thumb">
                        <div class="playlist-item-info">
                            <span class="playlist-item-title">${idx + 1}. ${escapeHtml(item.title)}</span>
                            <span class="playlist-item-duration">${item.duration || ''}</span>
                        </div>
                    `;
                    playlistItemsList.appendChild(card);
                });

                document.querySelectorAll('.playlist-checkbox').forEach(cb => {
                    cb.addEventListener('change', updatePlaylistDownloadBtnText);
                });
            }

            updatePlaylistDownloadBtnText();

        } else {
            playlistBadge.classList.add('hidden');
            playlistContainer.classList.add('hidden');
            videoThumbnail.src = data.thumbnail || 'https://via.placeholder.com/280x170?text=No+Thumbnail';
            videoDuration.textContent = data.duration || '00:00';

            downloadNowBtn.innerHTML = `
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                Start Download
            `;
        }

        if (data.views) {
            videoViews.textContent = data.views;
            videoViews.classList.remove('hidden');
        } else {
            videoViews.classList.add('hidden');
        }

        // Build Format Options Dropdown
        formatSelect.innerHTML = '';

        if (data.video_formats && data.video_formats.length > 0) {
            const videoOptGroup = document.createElement('optgroup');
            videoOptGroup.label = '── Video Resolutions (HD / SD) ──';
            data.video_formats.forEach(f => {
                const opt = document.createElement('option');
                opt.value = f.format_id;
                opt.dataset.label = f.label;
                opt.dataset.isAudio = 'false';
                opt.textContent = `${f.label} (${f.filesize_formatted})`;
                videoOptGroup.appendChild(opt);
            });
            formatSelect.appendChild(videoOptGroup);
        }

        if (data.presets && data.presets.length > 0) {
            const presetGroup = document.createElement('optgroup');
            presetGroup.label = '── Presets & Audio ──';
            data.presets.forEach(p => {
                const opt = document.createElement('option');
                opt.value = p.format_id;
                opt.dataset.label = p.label;
                opt.dataset.isAudio = p.is_audio ? 'true' : 'false';
                opt.textContent = p.label;
                presetGroup.appendChild(opt);
            });
            formatSelect.appendChild(presetGroup);
        }

        if (data.audio_formats && data.audio_formats.length > 0) {
            const audioGroup = document.createElement('optgroup');
            audioGroup.label = '── Audio Only Extracts ──';
            data.audio_formats.forEach(a => {
                const opt = document.createElement('option');
                opt.value = a.format_id;
                opt.dataset.label = a.label;
                opt.dataset.isAudio = 'true';
                opt.textContent = `${a.label} (${a.filesize_formatted})`;
                audioGroup.appendChild(opt);
            });
            formatSelect.appendChild(audioGroup);
        }

        resultCard.classList.remove('hidden');
        resultCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    // Start Download Trigger
    downloadNowBtn.addEventListener('click', async () => {
        if (!currentVideoData) return;

        const selectedOpt = formatSelect.options[formatSelect.selectedIndex];
        const formatId = selectedOpt ? selectedOpt.value : null;
        const formatLabel = selectedOpt ? selectedOpt.dataset.label : 'Standard';
        const isAudio = selectedOpt ? selectedOpt.dataset.isAudio === 'true' : false;
        const customOutputDir = outputPathInput.value.trim() || DEFAULT_PATH;

        if (currentVideoData.is_playlist) {
            const checkedBoxes = Array.from(document.querySelectorAll('.playlist-checkbox:checked'));
            if (checkedBoxes.length === 0) {
                showToast("Please select at least one video to download!");
                return;
            }

            showToast(`Queueing ${checkedBoxes.length} videos from playlist...`);

            for (const cb of checkedBoxes) {
                const itemUrl = cb.dataset.url;
                const itemTitle = cb.dataset.title;
                const itemThumb = cb.dataset.thumb;

                const payload = {
                    url: itemUrl,
                    title: itemTitle,
                    thumbnail: itemThumb,
                    format_id: formatId,
                    format_label: formatLabel,
                    is_audio: isAudio,
                    is_playlist: false,
                    output_dir: customOutputDir
                };

                try {
                    await fetch('/api/download', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                } catch (err) {
                    console.error("Failed to queue item", itemTitle, err);
                }
            }

            showToast(`Queued ${checkedBoxes.length} videos successfully!`);
            startPollingTasks();
            return;
        }

        const payload = {
            url: currentVideoData.resolved_url || urlInput.value.trim(),
            title: currentVideoData.title,
            thumbnail: currentVideoData.thumbnail || '',
            format_id: formatId,
            format_label: formatLabel,
            is_audio: isAudio,
            is_playlist: false,
            output_dir: customOutputDir
        };

        try {
            const res = await fetch('/api/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (data.task_id) {
                showToast("Download started!");
                startPollingTasks();
            } else {
                showToast("Error starting download.");
            }
        } catch (err) {
            showToast("Failed to initiate download.");
        }
    });

    // Poll Active Tasks
    function startPollingTasks() {
        if (!pollInterval) {
            pollTasks();
            pollInterval = setInterval(pollTasks, 1000);
        }
    }

    async function pollTasks() {
        try {
            const res = await fetch('/api/tasks');
            const tasks = await res.json();
            renderActiveTasks(tasks);
            fetchHistory();
        } catch (e) {
            console.error("Polling error", e);
        }
    }

    // Render Active Tasks
    function renderActiveTasks(tasks) {
        const activeTasks = tasks.filter(t => t.status === 'downloading' || t.status === 'queued' || t.status === 'paused');
        activeCount.textContent = activeTasks.length;

        if (activeTasks.length === 0) {
            emptyDownloads.classList.remove('hidden');
            downloadsList.querySelectorAll('.download-item').forEach(el => el.remove());
            return;
        }

        emptyDownloads.classList.add('hidden');

        activeTasks.forEach(task => {
            let item = document.getElementById(`task-${task.id}`);
            if (!item) {
                item = document.createElement('div');
                item.id = `task-${task.id}`;
                item.className = 'download-item';
                downloadsList.appendChild(item);
            }

            item.innerHTML = `
                <div class="item-top">
                    <div class="item-info">
                        <span class="item-title">${escapeHtml(task.title)}</span>
                        <span class="item-sub">${escapeHtml(task.format)} &bull; ${task.size || ''}</span>
                    </div>
                    <div class="item-actions-right" style="display:flex; align-items:center; gap:0.5rem;">
                        <span class="status-pill ${task.status}">${task.status}</span>
                        ${task.status === 'paused' ? 
                            `<button class="action-icon-btn btn-resume-task" data-id="${task.id}" title="Resume download">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                                Resume
                            </button>` :
                            `<button class="action-icon-btn btn-pause-task" data-id="${task.id}" title="Pause download">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg>
                                Pause
                            </button>`
                        }
                        <button class="action-icon-btn btn-cancel-task" data-id="${task.id}" title="Stop download">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                            Stop
                        </button>
                    </div>
                </div>
                <div class="progress-bar-container">
                    <div class="progress-fill" style="width: ${task.percent || 0}%"></div>
                </div>
                <div class="progress-stats">
                    <span>${(task.percent || 0).toFixed(1)}% downloaded</span>
                    <span>${task.speed || '0 KB/s'} &bull; ETA: ${task.eta || '--:--'}</span>
                </div>
            `;
        });

        downloadsList.querySelectorAll('.btn-cancel-task').forEach(btn => {
            btn.addEventListener('click', async () => {
                const taskId = btn.dataset.id;
                try {
                    await fetch('/api/cancel-task', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ task_id: taskId })
                    });
                    showToast("Download stopped");
                    pollTasks();
                } catch (e) {
                    showToast("Failed to stop download");
                }
            });
        });

        downloadsList.querySelectorAll('.btn-pause-task').forEach(btn => {
            btn.addEventListener('click', async () => {
                const taskId = btn.dataset.id;
                try {
                    await fetch('/api/pause-task', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ task_id: taskId })
                    });
                    pollTasks();
                } catch (e) {
                    showToast("Failed to pause download");
                }
            });
        });

        downloadsList.querySelectorAll('.btn-resume-task').forEach(btn => {
            btn.addEventListener('click', async () => {
                const taskId = btn.dataset.id;
                try {
                    await fetch('/api/resume-task', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ task_id: taskId })
                    });
                    pollTasks();
                } catch (e) {
                    showToast("Failed to resume download");
                }
            });
        });
    }

    // Fetch and Render History
    async function fetchHistory() {
        try {
            const res = await fetch('/api/history');
            const history = await res.json();
            renderHistory(history);
        } catch (e) {
            console.error("Failed to fetch history", e);
        }
    }

    function renderHistory(history) {
        if (!history || history.length === 0) {
            emptyHistory.classList.remove('hidden');
            historyList.querySelectorAll('.history-item').forEach(el => el.remove());
            return;
        }

        emptyHistory.classList.add('hidden');
        historyList.querySelectorAll('.history-item').forEach(el => el.remove());

        history.forEach(item => {
            const el = document.createElement('div');
            el.className = 'history-item';
            el.innerHTML = `
                <div class="item-info">
                    <span class="item-title">${escapeHtml(item.title)}</span>
                    <span class="item-sub">${escapeHtml(item.format)} &bull; Completed</span>
                </div>
                <div class="history-actions">
                    <button class="action-icon-btn open-file-btn" data-filepath="${escapeHtml(item.filepath || '')}">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                        Play
                    </button>
                    <button class="action-icon-btn open-folder-btn" data-filepath="${escapeHtml(item.filepath || '')}">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>
                        Finder
                    </button>
                </div>
            `;
            historyList.appendChild(el);
        });

        // Add action listeners
        document.querySelectorAll('.open-file-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const filepath = btn.dataset.filepath;
                if (filepath) {
                    fetch('/api/open-file', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ filepath })
                    });
                }
            });
        });

        document.querySelectorAll('.open-folder-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const filepath = btn.dataset.filepath;
                fetch('/api/open-folder', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ filepath })
                });
            });
        });
    }

    function escapeHtml(str) {
        if (!str) return '';
        return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
    }

    // Initial history fetch
    fetchHistory();
    startPollingTasks();
});
