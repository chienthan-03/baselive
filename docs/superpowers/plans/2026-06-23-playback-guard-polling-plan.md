# Playback Guard — Polling Without Interrupting Video

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent the 8-second dashboard poll from reloading video and flickering the highlight list while a clip is playing; defer UI sync until pause/end and offer an explicit banner when a newer clip is available.

**Architecture:** Add `isVideoPlaying()` guard around intrusive poll side-effects (`renderList`, `selectHighlight`, stream re-renders). Split `selectHighlight` into `syncDetailPanel` + `loadVideoForHighlight`. Queue deferred refreshes via `state.pendingRefresh` and flush on `pause`/`ended`. Show a click-to-update banner when `draft_clip_path` changes during playback.

**Tech Stack:** Vanilla JS (`src/api/static/js/app.js`), HTML, CSS. No new dependencies. Manual browser verification (no JS test harness in repo).

**Spec:** `docs/superpowers/specs/2026-06-23-playback-guard-polling-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `src/api/static/js/app.js` | Modify | Playback guard, refactor selection/video loading, guarded refresh, flush handlers |
| `src/api/static/index.html` | Modify | Clip-update banner element, cache-bust `?v=` |
| `src/api/static/css/styles.css` | Modify | `.clip-update-banner` styles |

---

## Task 1: Add State, Helpers, and DOM Refs

**Files:**
- Modify: `src/api/static/js/app.js` (state block ~L9–18, dom block ~L22–75)

- [ ] **Step 1: Extend state**

After `polling: null` in `state`, add:

```javascript
    pendingRefresh: false,
    clipUpdateAvailable: false,
```

- [ ] **Step 2: Add DOM ref for banner**

In `dom` object:

```javascript
    clipUpdateBanner: $('clip-update-banner'),
```

- [ ] **Step 3: Add helper functions** (place after `fmtDuration`, before Score Ring section)

```javascript
function isVideoPlaying() {
    return (
        !dom.videoWrapper.hidden &&
        Boolean(dom.videoPlayer.src) &&
        !dom.videoPlayer.paused &&
        !dom.videoPlayer.ended
    );
}

function clipSrcFromHighlight(h) {
    const clipToPlay = h?.clip_path || h?.draft_clip_path;
    if (!clipToPlay) return null;
    const fileName = clipToPlay.split(/[\\/]/).pop();
    return `/clips/${encodeURIComponent(fileName)}`;
}

function updateCardSelection(highlightId) {
    document.querySelectorAll('.highlight-card').forEach(c => {
        c.classList.toggle('selected', c.getAttribute('data-id') == highlightId);
    });
}

function showClipUpdateBanner() {
    if (!dom.clipUpdateBanner) return;
    dom.clipUpdateBanner.hidden = false;
}

function hideClipUpdateBanner() {
    if (!dom.clipUpdateBanner) return;
    dom.clipUpdateBanner.hidden = true;
}
```

---

## Task 2: Refactor `selectHighlight` into sync + load

**Files:**
- Modify: `src/api/static/js/app.js` (~L284–361)

- [ ] **Step 1: Add `syncDetailPanel`**

```javascript
function syncDetailPanel(h, { resetSliders = false } = {}) {
    dom.previewPlaceholder.hidden = true;
    dom.detailCard.hidden = false;

    dom.detailTitle.textContent = `Highlight #${h.id}`;
    dom.statusBadge.textContent = h.status;
    dom.statusBadge.className = `status-badge ${h.status}`;
    dom.detailStream.textContent = h.stream_id;
    dom.detailStart.textContent = fmtTime(h.start_pts);
    dom.detailEnd.textContent = fmtTime(h.end_pts);
    dom.detailDuration.textContent = fmtDuration(h.start_pts, h.end_pts);
    setScore(Math.max(0, Math.min(1, h.score ?? 0)));

    if (resetSliders) {
        state.startAdjust = 0;
        state.endAdjust = 0;
        dom.sliderStart.value = 0;
        dom.sliderEnd.value = 0;
        dom.sliderStartVal.textContent = '0s';
        dom.sliderEndVal.textContent = '0s';
    }

    const clipToPlay = h.clip_path || h.draft_clip_path;
    if (clipToPlay) {
        dom.videoWrapper.hidden = false;
        dom.videoOverlay.textContent =
            `Score ${Math.round((h.score ?? 0) * 100)}% · ${fmtDuration(h.start_pts, h.end_pts)}`;
    } else {
        dom.videoWrapper.hidden = true;
    }

    dom.btnApprove.disabled = h.status === 'APPROVED';
    dom.btnReject.disabled  = h.status === 'REJECTED';
}
```

- [ ] **Step 2: Add `loadVideoForHighlight`**

```javascript
function loadVideoForHighlight(h, { force = false } = {}) {
    const newSrc = clipSrcFromHighlight(h);
    if (!newSrc) {
        dom.videoPlayer.removeAttribute('data-src');
        dom.videoPlayer.src = '';
        dom.videoWrapper.hidden = true;
        return;
    }

    const currentSrc = dom.videoPlayer.getAttribute('data-src');
    if (!force && currentSrc === newSrc) return;

    const wasPlaying = !dom.videoPlayer.paused;
    const currentTime = dom.videoPlayer.currentTime;

    dom.videoPlayer.setAttribute('data-src', newSrc);
    dom.videoPlayer.src = newSrc;
    dom.videoPlayer.load();

    if (wasPlaying) {
        const onMetadata = () => {
            dom.videoPlayer.currentTime = currentTime;
            dom.videoPlayer.play().catch(() => {});
            dom.videoPlayer.removeEventListener('loadedmetadata', onMetadata);
        };
        dom.videoPlayer.addEventListener('loadedmetadata', onMetadata);
    }

    dom.videoWrapper.hidden = false;
}
```

- [ ] **Step 3: Replace `selectHighlight` body**

```javascript
function selectHighlight(h) {
    try {
        state.selected = h;
        state.clipUpdateAvailable = false;
        hideClipUpdateBanner();
        syncDetailPanel(h, { resetSliders: true });
        loadVideoForHighlight(h);
        updateCardSelection(h.id);
    } catch (err) {
        console.error('Error in selectHighlight:', err);
        showToast('❌ Lỗi hiển thị highlight: ' + err.message, 'error');
    }
}
```

- [ ] **Step 4: Manual verify**

Select a highlight → video loads, detail panel populates, sliders at 0.

---

## Task 3: Guard `refreshData` and `refreshStreams`

**Files:**
- Modify: `src/api/static/js/app.js` (~L375–420 approve handlers, ~L428–434 btn-refresh, ~L640–674)

- [ ] **Step 1: Add `highlightFieldsChanged`, `maybeFlagClipUpdate`, `maybeUpdateSelectedFromPoll`**

```javascript
function highlightFieldsChanged(a, b) {
    return (
        a.clip_path !== b.clip_path ||
        a.draft_clip_path !== b.draft_clip_path ||
        a.start_pts !== b.start_pts ||
        a.end_pts !== b.end_pts ||
        a.status !== b.status ||
        a.score !== b.score
    );
}

function maybeFlagClipUpdate() {
    if (!state.selected) return;
    const fresh = state.highlights.find(h => h.id === state.selected.id);
    if (!fresh) return;

    const newSrc = clipSrcFromHighlight(fresh);
    const currentSrc = dom.videoPlayer.getAttribute('data-src');
    if (newSrc && newSrc !== currentSrc) {
        state.clipUpdateAvailable = true;
        state.selected = fresh;
        showClipUpdateBanner();
    } else if (highlightFieldsChanged(fresh, state.selected)) {
        state.selected = fresh;
    }
}

function maybeUpdateSelectedFromPoll() {
    if (!state.selected) return;
    const fresh = state.highlights.find(h => h.id === state.selected.id);
    if (!fresh) return;
    if (!highlightFieldsChanged(fresh, state.selected)) return;

    const newSrc = clipSrcFromHighlight(fresh);
    const currentSrc = dom.videoPlayer.getAttribute('data-src');
    const srcChanged = newSrc !== currentSrc;

    state.selected = fresh;
    syncDetailPanel(fresh, { resetSliders: false });
    updateCardSelection(fresh.id);

    if (srcChanged && state.clipUpdateAvailable) {
        // Keep current video.src; banner remains until user clicks
        return;
    }
    if (srcChanged) {
        loadVideoForHighlight(fresh);
    }
}
```

- [ ] **Step 2: Replace `refreshData` and `refreshStreams` (with `force` built in)**

```javascript
async function refreshData({ force = false } = {}) {
    try {
        state.highlights = await api.getHighlights(state.streamFilter);

        if (!force && isVideoPlaying()) {
            state.pendingRefresh = true;
            maybeFlagClipUpdate();
            return;
        }

        state.pendingRefresh = false;
        if (!state.clipUpdateAvailable) hideClipUpdateBanner();
        renderStreamOptions();
        renderList();
        maybeUpdateSelectedFromPoll();
    } catch (e) {
        console.error('Fetch error:', e);
    }
}

async function refreshStreams({ force = false } = {}) {
    try {
        state.streams = await api.getStreams();
        if (!force && isVideoPlaying()) {
            state.pendingRefresh = true;
            return;
        }
        renderStreamOptions();
        renderActiveStreams();
    } catch (e) {
        console.error('Stream fetch error:', e);
    }
}
```

- [ ] **Step 3: Update approve / reject / adjust handlers**

Replace each block that ends with `selectHighlight(updated)`:

```javascript
await refreshData({ force: true });
const updated = state.highlights.find(h => h.id === state.selected?.id);
if (updated) {
    state.selected = updated;
    syncDetailPanel(updated, { resetSliders: false });
    updateCardSelection(updated.id);
}
```

Locations: `btnApprove` (~L381), `btnReject` (~L397), `btnAdjust` (~L418).

- [ ] **Step 4: Update manual refresh button**

```javascript
dom.btnRefresh.addEventListener('click', async () => {
    dom.btnRefresh.disabled = true;
    dom.btnRefresh.style.opacity = '0.6';
    await refreshStreams({ force: true });
    await refreshData({ force: true });
    dom.btnRefresh.disabled = false;
    dom.btnRefresh.style.opacity = '';
});
```

- [ ] **Step 5: Manual verify T1**

Play a clip, wait 30s → list should not flicker, video should not restart.

---

## Task 4: HTML Banner + CSS

**Files:**
- Modify: `src/api/static/index.html` (~L123–128, ~L11, ~L201)
- Modify: `src/api/static/css/styles.css`

- [ ] **Step 1: Add banner markup** inside `#video-wrapper`, before `#video-overlay-info`:

```html
<button type="button" class="clip-update-banner" id="clip-update-banner" hidden
        aria-label="Clip mới có sẵn, bấm để cập nhật">
    Clip mới có sẵn — bấm để cập nhật
</button>
```

- [ ] **Step 2: Add CSS** (append to `styles.css`):

```css
.clip-update-banner {
    position: absolute;
    top: 12px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 3;
    padding: 8px 16px;
    border: none;
    border-radius: 999px;
    background: hsla(265, 90%, 65%, 0.92);
    color: #fff;
    font-family: inherit;
    font-size: 0.85rem;
    font-weight: 600;
    cursor: pointer;
    box-shadow: 0 4px 20px hsla(265, 90%, 40%, 0.4);
}
.clip-update-banner:hover {
    background: hsla(265, 90%, 58%, 0.95);
}
.clip-update-banner:focus-visible {
    outline: 2px solid #fff;
    outline-offset: 2px;
}
```

`.video-wrapper` already has `position: relative` in `styles.css` — no change needed.

- [ ] **Step 3: Bump cache bust**

In `index.html`, change `v=1.0.1` → `v=1.0.2` on both `styles.css` and `app.js`.

---

## Task 5: Catch-Up Flush and Banner Click Handler

**Files:**
- Modify: `src/api/static/js/app.js` (near polling section ~L714)

- [ ] **Step 1: Add `flushPendingRefresh`**

```javascript
async function flushPendingRefresh() {
    if (!state.pendingRefresh) return;
    state.pendingRefresh = false;
    await refreshStreams({ force: true });
    await refreshData({ force: true });
}
```

- [ ] **Step 2: Register video event listeners**

```javascript
dom.videoPlayer.addEventListener('pause', () => { flushPendingRefresh(); });
dom.videoPlayer.addEventListener('ended', () => { flushPendingRefresh(); });
```

- [ ] **Step 3: Banner click handler**

```javascript
if (dom.clipUpdateBanner) {
    dom.clipUpdateBanner.addEventListener('click', () => {
        if (!state.selected) return;
        state.clipUpdateAvailable = false;
        hideClipUpdateBanner();
        loadVideoForHighlight(state.selected, { force: true });
        dom.videoPlayer.play().catch(() => {});
    });
}
```

- [ ] **Step 4: Full manual test pass**

Run all cases from spec §7 (T1–T6).

---

## Task 6: Final Verification

- [ ] **Step 1: Run API tests** (ensure no regressions)

```bash
pytest tests/api/test_routes.py -v
```

Expected: all pass (this change is frontend-only).

- [ ] **Step 2: Hard-refresh browser** (Ctrl+Shift+R) to load `v=1.0.2`

- [ ] **Step 3: Commit** (when user requests)

```bash
git add src/api/static/js/app.js src/api/static/index.html src/api/static/css/styles.css \
        docs/superpowers/specs/2026-06-23-playback-guard-polling-design.md \
        docs/superpowers/plans/2026-06-23-playback-guard-polling-plan.md
git commit -m "feat(dashboard): defer poll refresh while video is playing"
```

---

## Execution Notes

- `refreshHealth()` is intentionally **not** guarded — header status dot may still update every 8s; this does not affect playback.
- When `isVideoPlaying()` is false but video is visible (paused), `flushPendingRefresh` on pause may double-fetch — acceptable; guard with `pendingRefresh` prevents loops.
- If `.video-wrapper` lacks `position: relative`, banner positioning will be wrong — verify in browser.
