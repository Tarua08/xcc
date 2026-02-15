"""FastAPI Approval UI for the X Content Agent system.

Provides a web dashboard for reviewing, editing, approving, and rejecting
draft posts. Includes rate limiting and input validation.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

from ...shared.firestore_client import FirestoreClient
from ...shared.models import DraftPost, DraftStatus, DraftUpdateRequest
from ...shared.x_poster import get_poster

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate limiting (in-memory, simple for MVP)
# ---------------------------------------------------------------------------

_rate_limit_store: dict[str, list[float]] = defaultdict(list)
_rate_limit_lock = threading.Lock()
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 30  # requests per window


def _check_rate_limit(client_ip: str) -> bool:
    """Check if client has exceeded rate limit. Returns True if allowed."""
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW
    with _rate_limit_lock:
        _rate_limit_store[client_ip] = [
            t for t in _rate_limit_store[client_ip] if t > window_start
        ]
        if len(_rate_limit_store[client_ip]) >= RATE_LIMIT_MAX:
            return False
        _rate_limit_store[client_ip].append(now)
        return True


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="X Content Agent - Approval Dashboard",
    description="Human-in-the-loop review interface for AI-generated X posts",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("ALLOWED_ORIGINS", "http://localhost:8080")],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)

# Templates and static files
_base_dir = Path(__file__).parent
templates = Jinja2Templates(directory=str(_base_dir / "templates"))
if (_base_dir / "static").exists():
    app.mount("/static", StaticFiles(directory=str(_base_dir / "static")), name="static")

# Firestore client (initialized lazily)
_db: Optional[FirestoreClient] = None


def get_db() -> FirestoreClient:
    global _db
    if _db is None:
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        _db = FirestoreClient(project_id=project_id)
    return _db


# ---------------------------------------------------------------------------
# Rate limit middleware
# ---------------------------------------------------------------------------


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    response = await call_next(request)
    return response


# ---------------------------------------------------------------------------
# Dashboard routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, status: Optional[str] = None):
    """Main dashboard showing drafts filtered by status."""
    db = get_db()
    filter_status = DraftStatus(status) if status else None
    drafts = db.list_drafts(status=filter_status, limit=50)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "drafts": drafts,
            "current_filter": status or "all",
            "counts": {
                "pending": len(db.list_drafts(status=DraftStatus.PENDING)),
                "approved": len(db.list_drafts(status=DraftStatus.APPROVED)),
                "rejected": len(db.list_drafts(status=DraftStatus.REJECTED)),
            },
        },
    )


@app.get("/draft/{draft_id}", response_class=HTMLResponse)
async def view_draft(request: Request, draft_id: str):
    """View a single draft with edit capabilities."""
    db = get_db()
    draft = db.get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    # Also fetch the source item
    source_item = db.get_item(draft.item_id)
    return templates.TemplateResponse(
        "draft_detail.html",
        {
            "request": request,
            "draft": draft,
            "source_item": source_item,
            "char_count": len(draft.content),
        },
    )


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


@app.get("/api/drafts")
async def api_list_drafts(status: Optional[str] = None, limit: int = 50):
    """List drafts as JSON."""
    db = get_db()
    filter_status = DraftStatus(status) if status else None
    drafts = db.list_drafts(status=filter_status, limit=min(limit, 100))
    return {"drafts": [d.model_dump(mode="json") for d in drafts]}


@app.get("/api/drafts/{draft_id}")
async def api_get_draft(draft_id: str):
    """Get a single draft as JSON."""
    db = get_db()
    draft = db.get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return {"draft": draft.model_dump(mode="json")}


@app.patch("/api/drafts/{draft_id}")
async def api_update_draft(draft_id: str, update: DraftUpdateRequest):
    """Update a draft (edit content, add human lines, approve/reject)."""
    db = get_db()
    draft = db.get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    updates = {}
    if update.content is not None:
        if len(update.content) > 280:
            raise HTTPException(
                status_code=400,
                detail=f"Content exceeds 280 chars ({len(update.content)})",
            )
        updates["content"] = update.content

    if update.human_lines is not None:
        # Validate max 2 lines
        lines = [l for l in update.human_lines.strip().split("\n") if l.strip()]
        if len(lines) > 2:
            raise HTTPException(
                status_code=400, detail="Maximum 2 human signature lines"
            )
        updates["human_lines"] = update.human_lines

    if update.status is not None:
        updates["status"] = update.status.value
        if update.status in (DraftStatus.APPROVED, DraftStatus.REJECTED):
            updates["reviewed_at"] = datetime.now(timezone.utc).isoformat()

    if update.review_notes is not None:
        updates["review_notes"] = update.review_notes

    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")

    db.update_draft(draft_id, updates)
    updated_draft = db.get_draft(draft_id)
    return {"draft": updated_draft.model_dump(mode="json") if updated_draft else None}


@app.post("/api/drafts/{draft_id}/approve")
async def api_approve_draft(draft_id: str):
    """Approve a draft and post it to X if credentials are configured."""
    db = get_db()
    draft = db.get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    # Post to X if credentials are set
    poster = get_poster()
    tweet_result = None
    if poster.is_configured:
        tweet_result = poster.post_tweet(draft.content)
        if not tweet_result["success"]:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to post to X: {tweet_result['error']}",
            )

    updates = {
        "status": DraftStatus.APPROVED.value,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
    if tweet_result and tweet_result["success"]:
        updates["tweet_id"] = tweet_result["tweet_id"]
        updates["tweet_url"] = tweet_result["tweet_url"]

    db.update_draft(draft_id, updates)

    result = {"status": "approved", "draft_id": draft_id}
    if tweet_result and tweet_result["success"]:
        result["posted_to_x"] = True
        result["tweet_url"] = tweet_result["tweet_url"]
    else:
        result["posted_to_x"] = False
    return result


@app.post("/api/drafts/{draft_id}/reject")
async def api_reject_draft(draft_id: str):
    """Quick reject a draft."""
    db = get_db()
    draft = db.get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    db.update_draft(draft_id, {
        "status": DraftStatus.REJECTED.value,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"status": "rejected", "draft_id": draft_id}


# ---------------------------------------------------------------------------
# Weekly schedule
# ---------------------------------------------------------------------------


@app.get("/schedule", response_class=HTMLResponse)
async def weekly_schedule(request: Request):
    """Display the weekly ready-to-post schedule."""
    db = get_db()
    approved = db.get_approved_drafts_for_week()
    return templates.TemplateResponse(
        "schedule.html",
        {
            "request": request,
            "approved_drafts": approved,
            "total": len(approved),
        },
    )


@app.get("/api/schedule")
async def api_weekly_schedule():
    """Get the weekly schedule as JSON."""
    db = get_db()
    approved = db.get_approved_drafts_for_week()
    return {
        "schedule": [d.model_dump(mode="json") for d in approved],
        "total": len(approved),
    }


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    """Health check endpoint for Cloud Run — verifies Firestore connectivity."""
    try:
        db = get_db()
        db._db.collection("drafts").limit(1).get()
        return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        logger.error("Health check failed: %s", e)
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "error": str(e)},
        )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
