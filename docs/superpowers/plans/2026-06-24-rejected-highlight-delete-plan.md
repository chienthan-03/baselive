# Delete Button for Rejected Highlights - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a delete button to rejected highlights that removes both the video file from disk and the database record.

**Architecture:** Backend adds a DELETE endpoint that verifies status is REJECTED, deletes the files, and removes the DB record. Frontend adds delete buttons to rejected highlights with a confirmation dialog.

**Tech Stack:** FastAPI, SQLite, vanilla JS, ffmpeg-generated MP4 files

---

## File Structure

| File | Responsibility |
|------|---------------|
| `src/db/database.py` | Add `delete_highlight()` method to remove record and return file paths |
| `src/api/main.py` | Add DELETE `/api/highlights/{id}` endpoint with validation |
| `src/api/static/js/app.js` | Add delete button rendering, click handlers, and API client method |
| `src/api/static/css/styles.css` | Style delete button (red, compact) |
| `tests/db/test_database.py` | Test delete_highlight method |
| `tests/api/test_routes.py` | Test DELETE endpoint |

---

## Task 1: Database Layer - Add delete_highlight Method

**Files:**
- Modify: `src/db/database.py`
- Test: `tests/db/test_database.py`

- [ ] **Step 1: Write the failing test**

```python
def test_delete_highlight_removes_record_and_returns_paths(tmp_path):
    """delete_highlight should remove record and return file paths."""
    from src.db.database import Database
    
    db_path = tmp_path / "test.db"
    db = Database(str(db_path))
    db.init_db()
    
    # Insert a highlight
    h_id = db.insert_highlight(
        stream_id="test_stream",
        start_pts=10.0,
        end_pts=20.0,
        score=0.8,
        clip_path="output/clips/test.mp4",
        draft_clip_path="output/clips/draft_test.mp4",
        status="REJECTED",
    )
    
    # Delete it
    paths = db.delete_highlight(h_id)
    
    # Verify paths returned
    assert paths is not None
    assert paths["clip_path"] == "output/clips/test.mp4"
    assert paths["draft_clip_path"] == "output/clips/draft_test.mp4"
    
    # Verify record deleted
    cursor = db.conn.cursor()
    cursor.execute("SELECT * FROM highlights WHERE id = ?", (h_id,))
    assert cursor.fetchone() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/db/test_database.py::test_delete_highlight_removes_record_and_returns_paths -v`

Expected: FAIL with "AttributeError: 'Database' object has no attribute 'delete_highlight'"

- [ ] **Step 3: Implement delete_highlight method**

Add to `src/db/database.py` after `update_boundaries()` method (around line 162):

```python
    def delete_highlight(self, highlight_id: int) -> Optional[Dict[str, str]]:
        """Delete highlight and return file paths for cleanup.
        
        Returns:
            Dict with clip_path and draft_clip_path, or None if not found.
        """
        cursor = self.conn.cursor()
        
        # Get file paths before deletion
        cursor.execute(
            "SELECT clip_path, draft_clip_path FROM highlights WHERE id = ?",
            (highlight_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        
        paths = {
            "clip_path": row[0],
            "draft_clip_path": row[1],
        }
        
        # Delete the record
        cursor.execute("DELETE FROM highlights WHERE id = ?", (highlight_id,))
        self.conn.commit()
        
        return paths
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/db/test_database.py::test_delete_highlight_removes_record_and_returns_paths -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/db/test_database.py src/db/database.py
git commit -m "feat: add delete_highlight method to Database"
```

---

## Task 2: Backend API - Add DELETE Endpoint

**Files:**
- Modify: `src/api/main.py`
- Test: `tests/api/test_routes.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/api/test_routes.py`:

```python
def test_delete_rejected_highlight_success(client, test_db, tmp_path):
    """DELETE should remove rejected highlight and return success."""
    # Insert a rejected highlight
    cursor = test_db.conn.cursor()
    cursor.execute('''
        INSERT INTO highlights (stream_id, start_pts, end_pts, score, status, clip_path)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', ("s1", 10.0, 20.0, 0.8, "REJECTED", str(tmp_path / "clip.mp4")))
    test_db.conn.commit()
    
    # Create the file
    clip_path = tmp_path / "clip.mp4"
    clip_path.write_text("fake video")
    
    # Delete it
    response = client.delete("/api/highlights/1")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "deleted"
    assert str(clip_path) in data["deleted_paths"]
    
    # Verify DB record gone
    cursor.execute("SELECT * FROM highlights WHERE id = 1")
    assert cursor.fetchone() is None
    
    # Verify file deleted
    assert not clip_path.exists()


def test_delete_non_rejected_highlight_fails(client, test_db):
    """DELETE should fail if highlight is not REJECTED."""
    cursor = test_db.conn.cursor()
    cursor.execute('''
        INSERT INTO highlights (stream_id, start_pts, end_pts, score, status)
        VALUES (?, ?, ?, ?, ?)
    ''', ("s1", 10.0, 20.0, 0.8, "PENDING"))
    test_db.conn.commit()
    
    response = client.delete("/api/highlights/1")
    assert response.status_code == 403
    assert "Only rejected highlights" in response.json()["detail"]


def test_delete_nonexistent_highlight_returns_404(client):
    """DELETE should 404 if highlight doesn't exist."""
    response = client.delete("/api/highlights/999")
    assert response.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_routes.py::test_delete_rejected_highlight_success -v`

Expected: FAIL with "404 Not Found" (endpoint doesn't exist)

- [ ] **Step 3: Implement DELETE endpoint**

Add to `src/api/main.py` after `adjust_highlight()` endpoint (around line 196):

```python
@router.delete("/api/highlights/{highlight_id}")
def delete_highlight_endpoint(highlight_id: int, db: Database = Depends(get_db)):
    """Delete a rejected highlight and its video files."""
    import os
    
    h = db.get_highlight(highlight_id)
    if not h:
        raise HTTPException(status_code=404, detail="Highlight not found")
    
    if h["status"] != "REJECTED":
        raise HTTPException(
            status_code=403,
            detail="Only rejected highlights can be deleted"
        )
    
    # Get file paths before DB deletion
    paths = db.delete_highlight(highlight_id)
    
    # Delete files from disk
    deleted_paths = []
    for path_key in ["clip_path", "draft_clip_path"]:
        path = paths.get(path_key)
        if path and os.path.exists(path):
            try:
                os.remove(path)
                deleted_paths.append(path)
            except OSError as e:
                logging.getLogger(__name__).warning(
                    "Failed to delete file %s: %s", path, e
                )
    
    return {
        "id": highlight_id,
        "status": "deleted",
        "deleted_paths": deleted_paths
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/test_routes.py::test_delete_rejected_highlight_success tests/api/test_routes.py::test_delete_non_rejected_highlight_fails tests/api/test_routes.py::test_delete_nonexistent_highlight_returns_404 -v`

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add tests/api/test_routes.py src/api/main.py
git commit -m "feat: add DELETE /api/highlights/{id} endpoint"
```

---

## Task 3: Frontend API Client - Add deleteHighlight Method

**Files:**
- Modify: `src/api/static/js/app.js`

- [ ] **Step 1: Add deleteHighlight to API client**

Find the API client methods (around line 250-280) and add:

```javascript
deleteHighlight(id) {
  return this.request('DELETE', `/api/highlights/${id}`);
}
```

- [ ] **Step 2: Commit**

```bash
git add src/api/static/js/app.js
git commit -m "feat: add deleteHighlight API client method"
```

---

## Task 4: Frontend - Add Delete Button to Highlight Cards

**Files:**
- Modify: `src/api/static/js/app.js`
- Modify: `src/api/static/css/styles.css`

- [ ] **Step 1: Add delete button in renderList**

Find `renderList()` function and locate where highlight actions are rendered. After the reject button, add:

```javascript
// In renderList(), where highlight card actions are built
let actionsHtml = '';
if (h.status === 'PENDING') {
  actionsHtml = `
    <button class="btn btn-approve" data-id="${h.id}">Duyệt</button>
    <button class="btn btn-reject" data-id="${h.id}">Từ chối</button>
  `;
} else if (h.status === 'REJECTED') {
  actionsHtml = `
    <span class="badge badge-rejected">Đã từ chối</span>
    <button class="btn btn-delete" data-id="${h.id}" title="Xóa video">🗑️</button>
  `;
} else if (h.status === 'APPROVED') {
  actionsHtml = `<span class="badge badge-approved">Đã duyệt</span>`;
} else if (h.status === 'ADJUSTED') {
  actionsHtml = `<span class="badge badge-adjusted">Đã chỉnh sửa</span>`;
}
```

- [ ] **Step 2: Add delete button handler in event delegation**

Find where other button handlers are attached (around the approve/reject handlers) and add:

```javascript
// Delete button handler
if (target.classList.contains('btn-delete')) {
  const id = parseInt(target.dataset.id);
  handleDeleteHighlight(id);
}
```

- [ ] **Step 3: Implement handleDeleteHighlight function**

Add near other action handlers (around approve/reject handlers):

```javascript
async function handleDeleteHighlight(highlightId) {
  if (!confirm('Xóa video này? Không thể hoàn tác.')) {
    return;
  }
  
  try {
    await api.deleteHighlight(highlightId);
    
    // Remove from state
    state.highlights = state.highlights.filter(h => h.id !== highlightId);
    renderList();
    
    // If currently viewing this highlight, clear it
    if (state.selected?.id === highlightId) {
      state.selected = null;
      document.getElementById('video-wrapper').hidden = true;
      document.getElementById('placeholder').hidden = false;
      document.getElementById('detail-panel').classList.add('hidden');
    }
    
    showNotification('Đã xóa video', 'success');
  } catch (err) {
    console.error('Delete failed:', err);
    showNotification('Không thể xóa video: ' + err.message, 'error');
  }
}
```

- [ ] **Step 4: Add CSS for delete button**

Add to `src/api/static/css/styles.css`:

```css
.btn-delete {
  background: #ef4444;
  color: white;
  border: none;
  padding: 4px 8px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  margin-left: 8px;
}

.btn-delete:hover {
  background: #dc2626;
}
```

- [ ] **Step 5: Verify manually**

1. Start server: `uvicorn src.api.main:app --reload`
2. Open dashboard
3. Reject a highlight
4. Verify delete button appears
5. Click delete → confirm
6. Verify highlight disappears

- [ ] **Step 6: Commit**

```bash
git add src/api/static/js/app.js src/api/static/css/styles.css
git commit -m "feat: add delete button to rejected highlight cards"
```

---

## Task 5: Frontend - Add Delete Button to Detail Panel

**Files:**
- Modify: `src/api/static/js/app.js`

- [ ] **Step 1: Add delete button to detail panel**

Find `renderDetailPanel()` or where detail panel actions are rendered. Add delete button when status is REJECTED:

```javascript
function renderDetailPanel() {
  const h = state.selected;
  if (!h) return;
  
  const detailPanel = document.getElementById('detail-panel');
  const isRejected = h.status === 'REJECTED';
  const isPending = h.status === 'PENDING';
  
  let actionsHtml = '';
  
  if (isPending) {
    actionsHtml = `
      <button id="btn-approve" class="btn btn-primary">Duyệt</button>
      <button id="btn-reject" class="btn btn-secondary">Từ chối</button>
      <button id="btn-adjust" class="btn btn-tertiary">Chỉnh sửa</button>
    `;
  } else if (isRejected) {
    actionsHtml = `
      <span class="badge badge-rejected">Đã từ chối</span>
      <button id="btn-delete-video" class="btn btn-danger">🗑️ Xóa video</button>
    `;
  } else if (h.status === 'APPROVED') {
    actionsHtml = `<span class="badge badge-approved">Đã duyệt</span>`;
  } else if (h.status === 'ADJUSTED') {
    actionsHtml = `<span class="badge badge-adjusted">Đã chỉnh sửa</span>`;
  }
  
  // ... rest of render
  
  // Add event listeners
  if (isPending) {
    document.getElementById('btn-approve')?.addEventListener('click', () => handleApprove(h.id));
    document.getElementById('btn-reject')?.addEventListener('click', () => handleReject(h.id));
    document.getElementById('btn-adjust')?.addEventListener('click', () => handleAdjust(h.id));
  } else if (isRejected) {
    document.getElementById('btn-delete-video')?.addEventListener('click', () => handleDeleteHighlight(h.id));
  }
}
```

- [ ] **Step 2: Add CSS for btn-danger if not exists**

```css
.btn-danger {
  background: #ef4444;
  color: white;
  border: none;
  padding: 8px 16px;
  border-radius: 4px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.btn-danger:hover {
  background: #dc2626;
}
```

- [ ] **Step 3: Commit**

```bash
git add src/api/static/js/app.js src/api/static/css/styles.css
git commit -m "feat: add delete button to detail panel for rejected highlights"
```

---

## Task 6: Integration Testing

**Files:**
- Manual testing only (no automated integration tests needed for this feature)

- [ ] **Step 1: Test full flow**

```bash
# Clean start
rm -f base_live.db
rm -rf output/clips/*

# Start server
uvicorn src.api.main:app --reload
```

Test scenarios:
1. Create highlight → Reject → Delete → Verify gone from UI and disk
2. Create highlight → Approve → Verify no delete button
3. Create highlight → Reject → Refresh → Delete → Verify gone

- [ ] **Step 2: Verify file deletion**

```bash
# After deleting a highlight, check:
ls output/clips/  # Should not contain deleted clip
```

- [ ] **Step 3: Verify DB deletion**

```bash
sqlite3 base_live.db "SELECT * FROM highlights WHERE status='REJECTED';"
# Should return no results after deletion
```

- [ ] **Step 4: Final commit if all good**

```bash
git commit -m "test: verified delete functionality works end-to-end" --allow-empty
```

---

## Summary

This plan implements:
1. **Backend**: DELETE endpoint with validation (only REJECTED can be deleted)
2. **Database**: Method to delete record and return file paths
3. **Frontend**: Delete buttons in both list cards and detail panel
4. **UX**: Confirmation dialog, immediate UI update, error handling

All changes are minimal and follow existing patterns in the codebase.