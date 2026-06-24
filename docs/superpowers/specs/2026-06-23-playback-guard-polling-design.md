# Playback Guard — Polling Without Interrupting Video

> **Version:** 1.0  
> **Date:** 2026-06-23  
> **Status:** Approved  
> **Goal:** Stop the dashboard from interrupting video playback and flickering the highlight list during the 8-second polling cycle, while still syncing data when the user is not actively watching.

---

## 1. Problem Statement

The BaseLive dashboard polls the API every **8 seconds** (`startPolling()` in `src/api/static/js/app.js`). Each cycle:

1. Calls `refreshData()` → always runs `renderList()`, which **destroys and rebuilds** every highlight card.
2. If the selected highlight changed (`clip_path`, `draft_clip_path`, `start_pts`, `end_pts`, `status`, `score`), calls `selectHighlight(fresh)` which may **reload the `<video>` element** and **resets boundary sliders**.

### User-Reported Symptoms

| Symptom | When |
|---|---|
| Video restarts / stutters mid-playback | Every ~8s while watching |
| Highlight list flickers | Every ~8s |

### Root Causes

| # | Location | Cause |
|---|---|---|
| **RC1** | `refreshData()` | Unconditional `renderList()` on every poll |
| **RC2** | `refreshData()` → `selectHighlight()` | Poll triggers full detail re-render when metadata changes |
| **RC3** | `selectHighlight()` | Calls `videoPlayer.load()` when `clip_path` or `draft_clip_path` changes |
| **RC4** | `src/engine/pipeline.py` | Growing DRAFT highlights regenerate `draft_clip_path` frequently while ACTIVE — poll sees a new path every cycle |

### User Priority (Confirmed)

**Playback-first:** uninterrupted video is more important than real-time list/status updates while playing. Deferred catch-up on pause/end is acceptable.

---

## 2. Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Polling interval | Keep 8s | No change to backend; fix client-side behavior only |
| While video playing | Defer intrusive DOM + video updates | Matches playback-first priority |
| Growing draft clips | Show banner, do not auto-switch `video.src` | User chooses when to load longer clip |
| Metadata while playing | Skip detail panel updates from poll | Avoids slider reset side effect in `selectHighlight()` |
| Catch-up trigger | `pause`, `ended`, manual refresh button | Simple, predictable |
| List rendering | Full re-render when not playing; skip when playing | YAGNI — incremental DOM deferred unless needed later |
| Health / streams poll | Skip stream/list re-renders while playing; `refreshHealth` unchanged | Prevents flicker; header dot still updates |
| Explicit refresh | `refreshData({ force: true })` bypasses playback guard | Manual button + post-action sync |
| Catch-up on pause | Flush list/streams; **do not** auto-load newer clip if banner was shown | Preserves user-choice for draft updates |
| User actions during play | `syncDetailPanel(fresh)` after approve/reject/adjust — not full `selectHighlight` | Avoids slider reset + video reload |

---

## 3. Proposed Changes

### 3.1 New State Fields

**File:** `src/api/static/js/app.js`

```javascript
const state = {
    // ...existing...
    pendingRefresh: false,   // true when poll fetched data but UI update was deferred
    clipUpdateAvailable: false, // true when a newer draft/final clip exists while playing
};
```

### 3.2 Playback Guard Helper

```javascript
function isVideoPlaying() {
    return (
        !dom.videoWrapper.hidden &&
        dom.videoPlayer.src &&
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
```

### 3.3 Split `selectHighlight` Responsibilities

Refactor into three functions:

| Function | Responsibility | Resets sliders? | Touches `<video>`? |
|---|---|---|---|
| `selectHighlight(h)` | User-initiated selection | Yes | Yes (if src changed) |
| `syncDetailPanel(h, { resetSliders })` | Update badges, score, buttons, overlay | Configurable | No |
| `loadVideoForHighlight(h, { force })` | Set `video.src` / `load()` | No | Yes |

`selectHighlight(h)` becomes:

```javascript
function selectHighlight(h) {
    state.selected = h;
    state.clipUpdateAvailable = false;
    hideClipUpdateBanner();
    syncDetailPanel(h, { resetSliders: true });
    loadVideoForHighlight(h);
    updateCardSelection(h.id);
}
```

`syncDetailPanel` updates all detail DOM **except** the video element. When `resetSliders: false`, slider values and `state.startAdjust` / `state.endAdjust` are preserved.

### 3.4 Clip-Update Banner (HTML + CSS)

**File:** `src/api/static/index.html`

Add inside `.video-wrapper`, above the overlay:

```html
<button type="button" class="clip-update-banner" id="clip-update-banner" hidden
        aria-label="Clip mới có sẵn, bấm để cập nhật">
    Clip mới có sẵn — bấm để cập nhật
</button>
```

**File:** `src/api/static/css/styles.css`

Minimal banner styles: absolute top bar, accent background, pointer cursor, `z-index` above video.

Click handler: `loadVideoForHighlight(state.selected, { force: true })`, clear banner, set `clipUpdateAvailable = false`.

### 3.5 Guarded `refreshData()`

```javascript
async function refreshData({ force = false } = {}) {
    state.highlights = await api.getHighlights(state.streamFilter);

    if (!force && isVideoPlaying()) {
        state.pendingRefresh = true;
        maybeFlagClipUpdate(); // compare fresh selected vs current video src
        return; // no renderList, no selectHighlight, no renderStreamOptions
    }

    state.pendingRefresh = false;
    renderStreamOptions();
    renderList();
    maybeUpdateSelectedFromPoll();
}
```

**Call sites:**

| Caller | `force` | Notes |
|---|---|---|
| Polling (`startPolling`) | `false` (default) | Guarded |
| `btn-refresh` | `true` | Full sync even while playing |
| `flushPendingRefresh` | `true` | Catch-up after pause/end |
| Approve / reject / adjust handlers | `true` on `refreshData`, then `syncDetailPanel` | Never `selectHighlight` unless user picked new card |

`maybeFlagClipUpdate()`:

- Find `fresh` highlight matching `state.selected.id`
- If `clipSrcFromHighlight(fresh) !== dom.videoPlayer.getAttribute('data-src')`:
  - `state.clipUpdateAvailable = true`
  - Show banner
- Update `state.selected` in memory only (so approve/reject actions use fresh data) **without** calling `selectHighlight`

`maybeUpdateSelectedFromPoll()` (only when **not** playing, or `force === true`):

```
if metadata changed only (src unchanged):
  → syncDetailPanel(fresh, { resetSliders: false })

if src changed AND clipUpdateAvailable:
  → syncDetailPanel(fresh, { resetSliders: false })
  → keep current video.src, leave banner visible

if src changed AND NOT clipUpdateAvailable:
  → syncDetailPanel(fresh, { resetSliders: false })
  → loadVideoForHighlight(fresh)
```

### 3.6 Guarded `refreshStreams()`

```javascript
async function refreshStreams({ force = false } = {}) {
    state.streams = await api.getStreams();
    if (!force && isVideoPlaying()) {
        state.pendingRefresh = true;
        return;
    }
    renderStreamOptions();
    renderActiveStreams();
}
```

`btn-refresh` calls both `refreshStreams({ force: true })` and `refreshData({ force: true })`.

Health polling (`refreshHealth`) **continues unchanged** — only updates the header dot, no playback impact.

### 3.7 Post-Action Handlers (Approve / Reject / Adjust)

Replace trailing `selectHighlight(updated)` with:

```javascript
await refreshData({ force: true });
const updated = state.highlights.find(h => h.id === state.selected?.id);
if (updated) {
    state.selected = updated;
    syncDetailPanel(updated, { resetSliders: false });
    updateCardSelection(updated.id);
}
```

Only call `selectHighlight` when the user clicks a different highlight card.

### 3.8 Catch-Up on Pause / End

```javascript
async function flushPendingRefresh() {
    if (!state.pendingRefresh) return;
    state.pendingRefresh = false;
    await refreshStreams({ force: true });
    await refreshData({ force: true });
}

dom.videoPlayer.addEventListener('pause', flushPendingRefresh);
dom.videoPlayer.addEventListener('ended', flushPendingRefresh);
```

`maybeUpdateSelectedFromPoll` respects `clipUpdateAvailable`: if banner was shown, catch-up refreshes list/detail but **does not** auto-load the newer clip.

Manual refresh button (`btn-refresh`) always forces full refresh regardless of playback state.

### 3.9 Cache Bust

Bump `?v=` query on `app.js` and `styles.css` in `index.html` (e.g. `1.0.1` → `1.0.2`).

---

## 4. Behavior Matrix

| Scenario | Video playing | Action on poll |
|---|---|---|
| New highlight arrives | Yes | Deferred — list updates on pause |
| Selected highlight score changes | Yes | Deferred |
| `draft_clip_path` changes (growing) | Yes | Banner shown; video keeps current src |
| User pauses video | No (paused) | List catches up; if banner was visible, video src unchanged until click |
| User clicks refresh button | Either | `refreshStreams({ force: true })` + `refreshData({ force: true })` |
| User selects different highlight | N/A | `selectHighlight()` — always loads new clip |
| No video selected / placeholder visible | No | Normal poll behavior |

---

## 5. Non-Goals

- WebSocket / SSE push (out of scope)
- Incremental list DOM diff (deferred — add only if flicker persists after pause-guard)
- Changing backend draft regeneration frequency
- Adding Playwright / Vitest to the repo

---

## 6. Acceptance Criteria

1. While a clip is **playing**, the video does **not** call `load()` or change `src` due to polling alone.
2. While playing, the highlight list does **not** rebuild (no visible flicker).
3. While playing, boundary sliders are **not** reset by polling.
4. When a newer clip is available during playback, a **banner** appears; clicking it loads the new clip.
5. On **pause** or **video ended**, deferred highlights/streams render within one refresh cycle.
6. Manual **Làm mới** button still forces immediate full refresh.
7. Approve / reject / adjust actions update detail panel during playback **without** reloading video or resetting sliders.

---

## 7. Manual Test Plan

| # | Steps | Expected |
|---|---|---|
| T1 | Select highlight, press play, wait 30s | Video plays continuously; list static |
| T2 | During play, backend updates `draft_clip_path` (growing DRAFT) | Banner appears; video uninterrupted |
| T3 | Click banner | New clip loads and plays from start |
| T4 | Pause video after T1 | List catches up; video continues from same position; banner stays if clip update pending |
| T5 | Click Làm mới while playing | Full refresh (acceptable per manual refresh semantics) |
| T6 | No highlight selected | List still updates every 8s normally |

---

## 8. Files Touched

| File | Change |
|---|---|
| `src/api/static/js/app.js` | Playback guard, refactor select/sync/load, guarded refresh, event listeners |
| `src/api/static/index.html` | Clip-update banner markup, cache bust |
| `src/api/static/css/styles.css` | Banner styles |
