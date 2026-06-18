/**
 * BaseLive Dashboard — app.js
 * Handles: data fetching, rendering, interactions, video player, sliders, toasts
 */

// ── State ──────────────────────────────────────────────────────────────
const state = {
    highlights: [],
    streams: [],
    selected: null,      // currently selected highlight object
    filter: 'all',       // 'all' | 'DRAFT' | 'FINAL' | 'PENDING'
    streamFilter: 'all', // 'all' | stream_id
    startAdjust: 0,      // pre-roll delta (seconds, ≤ 0)
    endAdjust: 0,        // post-roll delta (seconds, ≥ 0)
    polling: null,       // setInterval handle
};

// ── DOM refs ───────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const dom = {
    list:           $('highlight-list'),
    emptyState:     $('empty-state'),
    queueCount:     $('queue-count'),
    filterTabs:     document.querySelectorAll('.filter-tab'),

    previewPlaceholder: $('preview-placeholder'),
    videoWrapper:       $('video-wrapper'),
    videoPlayer:        $('video-player'),
    videoOverlay:       $('video-overlay-info'),
    detailCard:         $('detail-card'),

    detailTitle:    $('detail-title'),
    statusBadge:    $('detail-status-badge'),
    detailStream:   $('detail-stream'),
    detailStart:    $('detail-start'),
    detailEnd:      $('detail-end'),
    detailDuration: $('detail-duration'),

    scoreCircle:    $('score-circle'),
    scoreLabel:     $('score-label'),

    sliderStart:    $('slider-start'),
    sliderStartVal: $('slider-start-val'),
    sliderEnd:      $('slider-end'),
    sliderEndVal:   $('slider-end-val'),
    btnAdjust:      $('btn-adjust'),

    btnApprove:     $('btn-approve'),
    btnReject:      $('btn-reject'),
    btnRefresh:     $('btn-refresh'),
    toast:          $('toast'),

    rejectModal:        $('reject-modal'),
    rejectReasonSelect: $('reject-reason-select'),
    btnRejectCancel:    $('btn-reject-cancel'),
    btnRejectConfirm:   $('btn-reject-confirm'),

    streamSelect:       $('stream-select'),

    detailContentType:  $('detail-content-type'),
    qualityWarnings:    $('quality-warnings'),

    healthDot:          $('health-status-dot'),
    healthLabel:        $('health-status-label'),
};

// ── API helpers ────────────────────────────────────────────────────────
const api = {
    async getHighlights(streamId) {
        const params = new URLSearchParams();
        if (streamId && streamId !== 'all') {
            params.set('stream_id', streamId);
        }
        const qs = params.toString();
        const res = await fetch(`/api/highlights${qs ? `?${qs}` : ''}`);
        if (!res.ok) throw new Error('Failed to fetch highlights');
        return res.json();
    },
    async getStreams() {
        const res = await fetch('/api/streams');
        if (!res.ok) throw new Error('Failed to fetch streams');
        return res.json();
    },
    async approve(id) {
        const res = await fetch(`/api/highlights/${id}/approve`, { method: 'POST' });
        if (!res.ok) throw new Error('Failed to approve');
        return res.json();
    },
    async reject(id) {
        const res = await fetch(`/api/highlights/${id}/reject`, { method: 'POST' });
        if (!res.ok) throw new Error('Failed to reject');
        return res.json();
    },
    async adjust(id, start_pts, end_pts) {
        const res = await fetch(`/api/highlights/${id}/adjust`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ start_pts, end_pts }),
        });
        if (!res.ok) throw new Error('Failed to adjust');
        return res.json();
    },
    async getHealthReady() {
        const res = await fetch('/api/health/ready');
        const data = await res.json().catch(() => ({}));
        return { ok: res.ok, status: data.status, ready: data.ready };
    },
};

// ── Toast ──────────────────────────────────────────────────────────────
let toastTimer = null;
function showToast(msg, type = 'default') {
    const colors = {
        success: 'hsla(175,80%,50%,.25)',
        error:   'hsla(348,86%,61%,.25)',
        info:    'hsla(265,90%,65%,.25)',
        default: 'hsla(230,14%,18%,.85)',
    };
    dom.toast.textContent = msg;
    dom.toast.style.borderColor = colors[type] ?? colors.default;
    dom.toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => dom.toast.classList.remove('show'), 2800);
}

// ── Formatting helpers ─────────────────────────────────────────────────
function fmtTime(s) {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60).toString().padStart(2, '0');
    return `${m}:${sec}`;
}

function fmtDuration(start, end) {
    const d = end - start;
    if (d < 60) return `${d.toFixed(1)}s`;
    return `${(d / 60).toFixed(1)} min`;
}

// ── Score Ring ─────────────────────────────────────────────────────────
// SVG gradient injection (once)
const svgNs = 'http://www.w3.org/2000/svg';
(function injectGradient() {
    const svg = document.querySelector('.score-svg');
    if (!svg) return;
    const defs = document.createElementNS(svgNs, 'defs');
    const grad = document.createElementNS(svgNs, 'linearGradient');
    grad.setAttribute('id', 'score-grad');
    grad.setAttribute('x1', '0%'); grad.setAttribute('y1', '0%');
    grad.setAttribute('x2', '100%'); grad.setAttribute('y2', '100%');
    const s1 = document.createElementNS(svgNs, 'stop');
    s1.setAttribute('offset', '0%'); s1.setAttribute('stop-color', 'hsl(265,90%,65%)');
    const s2 = document.createElementNS(svgNs, 'stop');
    s2.setAttribute('offset', '100%'); s2.setAttribute('stop-color', 'hsl(175,80%,50%)');
    grad.append(s1, s2);
    defs.append(grad);
    svg.prepend(defs);
    dom.scoreCircle.setAttribute('stroke', 'url(#score-grad)');
})();

function setScore(score) {
    const circumference = 113; // 2π × 18
    const offset = circumference - score * circumference;
    dom.scoreCircle.style.strokeDashoffset = offset;
    dom.scoreLabel.textContent = Math.round(score * 100);
}

// ── Filtering ──────────────────────────────────────────────────────────
function getVisibleHighlights() {
    return state.highlights.filter(h => getDuration(h) >= MIN_DURATION_SEC);
}

function applyFilter(highlights) {
    let result = highlights;
    if (state.streamFilter !== 'all') {
        result = result.filter(h => h.stream_id === state.streamFilter);
    }
    if (state.filter === 'all') return result;
    if (state.filter === 'PENDING') {
        return result.filter(h => h.status === 'PENDING');
    }
    return result.filter(h => getHighlightType(h) === state.filter);
}

// ── Rendering ──────────────────────────────────────────────────────────
function renderList() {
    const filtered = state.filter === 'all'
        ? state.highlights
        : state.highlights.filter(h => h.status === state.filter);

    dom.queueCount.textContent = filtered.length;

    // Clear non-empty children (keep empty-state)
    Array.from(dom.list.children).forEach(child => {
        if (child !== dom.emptyState) child.remove();
    });

    if (filtered.length === 0) {
        dom.emptyState.hidden = false;
        return;
    }
    dom.emptyState.hidden = true;

    filtered.forEach((h, i) => {
        const card = document.createElement('div');
        card.className = 'highlight-card';
        card.setAttribute('role', 'listitem');
        card.setAttribute('tabindex', '0');
        card.setAttribute('aria-label', `Highlight #${h.id} - ${h.status}`);
        card.setAttribute('data-id', h.id);
        card.setAttribute('data-status', h.status);
        card.style.animationDelay = `${i * 40}ms`;

        if (state.selected?.id === h.id) card.classList.add('selected');

        const dur = fmtDuration(h.start_pts, h.end_pts);
        const scorePercent = Math.round((h.score ?? 0) * 100);

        card.innerHTML = `
            <div class="card-top">
                <span class="card-id">Highlight #${h.id}</span>
                <span class="card-status card-status--${h.status}">${h.status}</span>
            </div>
            <div class="card-stream" title="${h.stream_id}">${h.stream_id}</div>
            <div class="card-time">
                <span>${fmtTime(h.start_pts)}</span>
                <span style="color:var(--text-muted)">→</span>
                <span>${fmtTime(h.end_pts)}</span>
                <span style="margin-left:4px;color:var(--accent-primary)">${dur}</span>
            </div>
            <div class="card-score-bar">
                <div class="card-score-fill" style="width:${scorePercent}%"></div>
            </div>
        `;

        card.addEventListener('click', () => selectHighlight(h));
        card.addEventListener('keydown', e => {
            if (e.key === 'Enter' || e.key === ' ') selectHighlight(h);
        });

        dom.list.appendChild(card);
    });
}

// ── Select Highlight ───────────────────────────────────────────────────
function selectHighlight(h) {
    state.selected = h;
    state.startAdjust = 0;
    state.endAdjust = 0;

    // Update sidebar selection
    document.querySelectorAll('.highlight-card').forEach(c => {
        c.classList.toggle('selected', c.getAttribute('data-id') == h.id);
    });

    // Show detail panel
    dom.previewPlaceholder.hidden = true;
    dom.detailCard.hidden = false;

    // Populate details
    dom.detailTitle.textContent = `Highlight #${h.id}`;

    // Status badge
    dom.statusBadge.textContent = h.status;
    dom.statusBadge.className = `status-badge ${h.status}`;

    dom.detailStream.textContent = h.stream_id;
    dom.detailStart.textContent = fmtTime(h.start_pts);
    dom.detailEnd.textContent = fmtTime(h.end_pts);
    dom.detailDuration.textContent = fmtDuration(h.start_pts, h.end_pts);

    // Score ring
    setScore(Math.max(0, Math.min(1, h.score ?? 0)));

    // Reset sliders
    dom.sliderStart.value = 0;
    dom.sliderEnd.value = 0;
    dom.sliderStartVal.textContent = '0s';
    dom.sliderEndVal.textContent = '0s';

    // Video player
    if (h.clip_path) {
        // Extract filename from path for URL
        const fileName = h.clip_path.split(/[\\/]/).pop();
        dom.videoWrapper.hidden = false;
        dom.videoPlayer.src = `/clips/${encodeURIComponent(fileName)}`;
        dom.videoPlayer.load();
        dom.videoOverlay.textContent = `Score ${Math.round((h.score ?? 0) * 100)}% · ${fmtDuration(h.start_pts, h.end_pts)}`;
    } else {
        dom.videoWrapper.hidden = true;
    }

    // Button states
    dom.btnApprove.disabled = h.status === 'APPROVED';
    dom.btnReject.disabled  = h.status === 'REJECTED';
}

// ── Sliders ────────────────────────────────────────────────────────────
dom.sliderStart.addEventListener('input', () => {
    state.startAdjust = parseFloat(dom.sliderStart.value);
    dom.sliderStartVal.textContent = `${state.startAdjust}s`;
});

dom.sliderEnd.addEventListener('input', () => {
    state.endAdjust = parseFloat(dom.sliderEnd.value);
    dom.sliderEndVal.textContent = `+${state.endAdjust}s`;
});

// ── Actions ────────────────────────────────────────────────────────────
dom.btnApprove.addEventListener('click', async () => {
    if (!state.selected) return;
    try {
        dom.btnApprove.disabled = true;
        await api.approve(state.selected.id);
        showToast('✅ Highlight đã được phê duyệt!', 'success');
        await refreshData();
        // Re-select the updated version
        const updated = state.highlights.find(h => h.id === state.selected?.id);
        if (updated) selectHighlight(updated);
    } catch (e) {
        showToast('❌ Lỗi khi phê duyệt. Thử lại.', 'error');
        dom.btnApprove.disabled = false;
    }
});

dom.btnReject.addEventListener('click', async () => {
    if (!state.selected) return;
    try {
        dom.btnReject.disabled = true;
        await api.reject(state.selected.id);
        showToast('🚫 Highlight đã bị từ chối.', 'info');
        await refreshData();
        const updated = state.highlights.find(h => h.id === state.selected?.id);
        if (updated) selectHighlight(updated);
    } catch (e) {
        showToast('❌ Lỗi khi từ chối. Thử lại.', 'error');
        dom.btnReject.disabled = false;
    }
});

dom.btnAdjust.addEventListener('click', async () => {
    if (!state.selected) return;
    const newStart = state.selected.start_pts + state.startAdjust;
    const newEnd   = state.selected.end_pts + state.endAdjust;
    if (newStart >= newEnd) {
        showToast('⚠️ Điểm bắt đầu phải nhỏ hơn điểm kết thúc.', 'error');
        return;
    }
    try {
        dom.btnAdjust.disabled = true;
        await api.adjust(state.selected.id, newStart, newEnd);
        showToast('✏️ Đã cập nhật ranh giới clip.', 'success');
        await refreshData();
        const updated = state.highlights.find(h => h.id === state.selected?.id);
        if (updated) selectHighlight(updated);
    } catch (e) {
        showToast('❌ Lỗi khi cập nhật. Thử lại.', 'error');
    } finally {
        dom.btnAdjust.disabled = false;
    }
});

// ── Refresh Button ─────────────────────────────────────────────────────
dom.btnRefresh.addEventListener('click', async () => {
    dom.btnRefresh.disabled = true;
    dom.btnRefresh.style.opacity = '0.6';
    await refreshData();
    dom.btnRefresh.disabled = false;
    dom.btnRefresh.style.opacity = '';
    showToast('🔄 Đã làm mới danh sách.', 'default');
});

// ── Filter Tabs ────────────────────────────────────────────────────────
dom.filterTabs.forEach(tab => {
    tab.addEventListener('click', () => {
        dom.filterTabs.forEach(t => {
            t.classList.remove('active');
            t.setAttribute('aria-selected', 'false');
        });
        tab.classList.add('active');
        tab.setAttribute('aria-selected', 'true');
        state.filter = tab.dataset.filter;
        renderList();
    });
});

// ── Stream selector ────────────────────────────────────────────────────
function renderStreamOptions() {
    const select = dom.streamSelect;
    const current = state.streamFilter;
    const knownIds = new Set(state.streams.map(s => s.stream_id));

    // Include stream IDs from highlights not yet in active list
    state.highlights.forEach(h => {
        if (h.stream_id) knownIds.add(h.stream_id);
    });

    select.innerHTML = '<option value="all">Tất cả streams</option>';
    [...knownIds].sort().forEach(streamId => {
        const opt = document.createElement('option');
        opt.value = streamId;
        opt.textContent = streamId;
        const active = state.streams.find(s => s.stream_id === streamId);
        if (active?.running) {
            opt.textContent += ' ●';
        }
        select.appendChild(opt);
    });

    if ([...select.options].some(o => o.value === current)) {
        select.value = current;
    } else {
        select.value = 'all';
        state.streamFilter = 'all';
    }
}

dom.streamSelect.addEventListener('change', async () => {
    state.streamFilter = dom.streamSelect.value;
    await refreshData();
});

// ── Data fetching ──────────────────────────────────────────────────────
async function refreshStreams() {
    try {
        state.streams = await api.getStreams();
        renderStreamOptions();
    } catch (e) {
        console.error('Stream fetch error:', e);
    }
}

async function refreshData() {
    try {
        state.highlights = await api.getHighlights(state.streamFilter);
        renderStreamOptions();
        renderList();
    } catch (e) {
        console.error('Fetch error:', e);
    }
}

// ── Health status dot ──────────────────────────────────────────────────
function setHealthStatus(mode) {
    const dot = dom.healthDot;
    const label = dom.healthLabel;
    if (!dot || !label) return;

    dot.className = 'status-dot';
    if (mode === 'ok') {
        dot.classList.add('status-dot--ok');
        dot.setAttribute('aria-label', 'Trạng thái hệ thống: sẵn sàng');
        label.textContent = 'Hệ thống sẵn sàng';
    } else if (mode === 'degraded') {
        dot.classList.add('status-dot--degraded');
        dot.setAttribute('aria-label', 'Trạng thái hệ thống: suy giảm');
        label.textContent = 'Hệ thống suy giảm';
    } else {
        dot.classList.add('status-dot--error');
        dot.setAttribute('aria-label', 'Trạng thái hệ thống: không phản hồi');
        label.textContent = 'Không phản hồi';
    }
}

async function refreshHealth() {
    try {
        const { ok, status } = await api.getHealthReady();
        if (ok && status === 'ok') {
            setHealthStatus('ok');
        } else if (status === 'degraded') {
            setHealthStatus('degraded');
        } else {
            setHealthStatus('error');
        }
    } catch (e) {
        console.error('Health check error:', e);
        setHealthStatus('error');
    }
}

// ── Polling (every 8 seconds) ──────────────────────────────────────────
function startPolling() {
    state.polling = setInterval(async () => {
        await refreshHealth();
        await refreshStreams();
        await refreshData();
    }, 8000);
}

// ── Init ───────────────────────────────────────────────────────────────
(async () => {
    await refreshHealth();
    await refreshStreams();
    await refreshData();
    startPolling();
})();
