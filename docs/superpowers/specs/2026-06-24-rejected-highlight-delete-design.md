# Delete Button for Rejected Highlights

> **Version:** 1.0  
> **Date:** 2026-06-24  
> **Status:** Approved  
> **Goal:** Allow editors to manually delete rejected highlight videos from both disk and database.

---

## 1. Problem Statement

Currently, when a highlight is rejected:
- Status changes to `REJECTED` in the database
- Video files remain in `output/clips/` forever
- No way to clean up disk space from the UI

### User Story
> As an editor, after rejecting a highlight, I want to delete the video file to free up disk space, without deleting it immediately upon rejection (in case I change my mind).

---

## 2. Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Delete trigger | Manual button click | Prevents accidental deletion |
| Button location | Both list card and detail panel | Convenient access from anywhere |
| Confirmation | Native confirm dialog | Simple, no extra UI code needed |
| Deletion type | Hard delete (file + DB record) | Clean, no orphaned data |
| Who can delete | Any editor (no extra auth) | Simple, aligns with approve/reject permissions |

---

## 3. API Changes

### New Endpoint

```http
DELETE /api/highlights/{highlight_id}
```

**Request:**
- Method: `DELETE`
- Path param: `highlight_id` (integer)

**Response:**
```json
{
  "id": 123,
  "status": "deleted",
  "deleted_paths": ["output/clips/highlight_xxx.mp4"]
}
```

**Errors:**
- `404` - Highlight not found
- `403` - Highlight not in REJECTED status (can only delete rejected)
- `500` - File deletion failed

**Implementation Details:**
1. Check highlight exists
2. Verify `status === 'REJECTED'`
3. Delete files at `clip_path` and `draft_clip_path` if exist
4. Delete DB record (or soft delete - see Alternatives)
5. Return confirmation

---

## 4. Frontend Changes

### 4.1 Card List (`renderList()`)

When `highlight.status === 'REJECTED'`, add delete button:

```javascript
// In highlight card
<button class="btn-delete" data-id="${h.id}" title="Xóa video">
  🗑️
</button>
```

**Styling:** Red color, smaller than approve/reject buttons

### 4.2 Detail Panel

Add to action bar when viewing rejected highlight:

```javascript
if (selected.status === 'REJECTED') {
  actionsHtml += `
    <button id="btn-delete-video" class="btn btn-danger">
      🗑️ Xóa video
    </button>
  `;
}
```

### 4.3 Delete Handler

```javascript
async function handleDeleteHighlight(highlightId) {
  if (!confirm('Xóa video này? Không thể hoàn tác.')) {
    return;
  }
  
  try {
    await api.deleteHighlight(highlightId);
    // Remove from UI
    state.highlights = state.highlights.filter(h => h.id !== highlightId);
    renderList();
    
    // If currently viewing this highlight, close detail panel
    if (state.selected?.id === highlightId) {
      closeDetailPanel();
    }
  } catch (err) {
    showError('Không thể xóa video: ' + err.message);
  }
}
```

### 4.4 API Client Addition

```javascript
deleteHighlight(id) {
  return this.request('DELETE', `/api/highlights/${id}`);
}
```

---

## 5. Backend Changes

### 5.1 Database Method

Add to `Database` class:

```python
def delete_highlight(self, highlight_id: int) -> Optional[Dict]:
    """Delete highlight and return deleted file paths."""
    cursor = self.conn.cursor()
    
    # Get file paths before deletion
    cursor.execute(
        "SELECT clip_path, draft_clip_path FROM highlights WHERE id = ?",
        (highlight_id,)
    )
    row = cursor.fetchone()
    if not row:
        return None
    
    paths = {"clip_path": row[0], "draft_clip_path": row[1]}
    
    # Delete record
    cursor.execute("DELETE FROM highlights WHERE id = ?", (highlight_id,))
    self.conn.commit()
    
    return paths
```

### 5.2 API Route

Add to `main.py`:

```python
@router.delete("/api/highlights/{highlight_id}")
def delete_highlight_endpoint(highlight_id: int, db: Database = Depends(get_db)):
    """Delete a rejected highlight and its video files."""
    h = db.get_highlight(highlight_id)
    if not h:
        raise HTTPException(status_code=404, detail="Highlight not found")
    
    if h["status"] != "REJECTED":
        raise HTTPException(
            status_code=403, 
            detail="Only rejected highlights can be deleted"
        )
    
    # Get file paths
    paths = db.delete_highlight(highlight_id)
    
    # Delete files from disk
    deleted_paths = []
    for path_key in ["clip_path", "draft_clip_path"]:
        path = paths.get(path_key)
        if path and os.path.exists(path):
            try:
                os.remove(path)
                deleted_paths.append(path)
            except OSError:
                pass  # Log warning but don't fail
    
    return {
        "id": highlight_id,
        "status": "deleted",
        "deleted_paths": deleted_paths
    }
```

---

## 6. UI/UX Details

### Button States

| State | Visibility | Style |
|-------|-----------|-------|
| `PENDING` | Hidden | - |
| `APPROVED` | Hidden | - |
| `ADJUSTED` | Hidden | - |
| `REJECTED` | Visible | Red trash icon |
| `REJECTED_BY_AI` | Visible | Red trash icon (if shown in UI) |

### Confirmation Dialog

```
┌─────────────────────────────────┐
│  Xóa video này?                 │
│                                 │
│  Không thể hoàn tác.            │
│                                 │
│  [Hủy]        [Xóa]             │
└─────────────────────────────────┘
```

### Success Feedback

- Highlight removed from list immediately
- Toast notification: "Đã xóa video"
- Detail panel closes if viewing deleted highlight

---

## 7. Error Handling

| Scenario | Behavior |
|----------|----------|
| File already deleted | Silently continue, delete DB record |
| File in use/locked | Show error: "File đang được sử dụng" |
| DB delete fails | Show error, don't delete files |
| Network error | Show error, highlight stays in list |

---

## 8. Security Considerations

- Only delete files within `output/clips/` (path traversal check)
- Only delete if status is `REJECTED` (prevents deleting active/approved content)
- No additional auth needed (same as approve/reject permissions)

---

## 9. Future Enhancements (Out of Scope)

- Bulk delete multiple rejected highlights
- Auto-delete after X days
- "Recently deleted" folder for recovery
- Admin audit log

---

## 10. Files Changed

| File | Change |
|------|--------|
| `src/api/main.py` | Add DELETE endpoint |
| `src/db/database.py` | Add `delete_highlight()` method |
| `src/api/static/js/app.js` | Add delete handler, button rendering, API client |
| `src/api/static/css/styles.css` | Style delete button |
| `src/api/static/index.html` | (Optional) Add delete confirmation modal if not using native confirm |

---

## 11. Acceptance Criteria

1. [ ] Rejected highlights show delete button in list
2. [ ] Rejected highlights show delete button in detail panel
3. [ ] Non-rejected highlights never show delete button
4. [ ] Click delete shows confirmation dialog
5. [ ] Cancel leaves everything unchanged
6. [ ] Confirm deletes file from disk
7. [ ] Confirm deletes record from DB
8. [ ] Deleted highlight disappears from UI immediately
9. [ ] If viewing deleted highlight, detail panel closes
10. [ ] Error messages are in Vietnamese