import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import database
import gmail_client
import pipeline


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    task = asyncio.create_task(_poll_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="FocusVA", lifespan=lifespan)


async def _poll_loop() -> None:
    """Background loop: sleep first, then poll, so tests complete before first cycle."""
    while True:
        await asyncio.sleep(config.POLL_INTERVAL_SECONDS)
        try:
            emails = gmail_client.fetch_new_emails()
            for email in emails:
                with database.get_conn() as conn:
                    exists = conn.execute(
                        "SELECT id FROM emails WHERE gmail_message_id = ?",
                        (email["gmail_message_id"],),
                    ).fetchone()
                if not exists:
                    pipeline.process_email(email)
        except Exception as exc:
            print(f"[poller error] {exc}")


# --- Endpoints ---

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/emails")
def list_emails(
    status: Optional[str] = None,
    classification: Optional[str] = None,
):
    query = """
        SELECT e.*, d.body AS draft_body
        FROM emails e
        LEFT JOIN drafts d ON d.email_id = e.id
        WHERE 1=1
    """
    params: list = []
    if status:
        query += " AND e.status = ?"
        params.append(status)
    if classification:
        query += " AND e.classification = ?"
        params.append(classification)
    query += " ORDER BY e.received_at DESC"

    with database.get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


@app.get("/emails/{email_id}")
def get_email(email_id: int):
    with database.get_conn() as conn:
        email = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
        if not email:
            raise HTTPException(status_code=404, detail="Email not found")
        jd = conn.execute("SELECT data FROM job_data WHERE email_id = ?", (email_id,)).fetchone()
        draft = conn.execute("SELECT * FROM drafts WHERE email_id = ?", (email_id,)).fetchone()

    return {
        "email": dict(email),
        "job_data": json.loads(jd["data"]) if jd else {},
        "draft": dict(draft) if draft else None,
    }


class DraftUpdate(BaseModel):
    body: str


@app.put("/emails/{email_id}/draft")
def update_draft(email_id: int, update: DraftUpdate):
    with database.get_conn() as conn:
        draft = conn.execute("SELECT id FROM drafts WHERE email_id = ?", (email_id,)).fetchone()
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")
        conn.execute("UPDATE drafts SET body = ? WHERE email_id = ?", (update.body, email_id))
    return {"ok": True}


class ApproveRequest(BaseModel):
    approved_by: str = "staff"


@app.post("/emails/{email_id}/approve")
def approve_email(email_id: int, req: ApproveRequest):
    with database.get_conn() as conn:
        email = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
        if not email:
            raise HTTPException(status_code=404, detail="Email not found")
        if email["status"] != "pending":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot approve email with status '{email['status']}'",
            )
        draft = conn.execute("SELECT * FROM drafts WHERE email_id = ?", (email_id,)).fetchone()
        if not draft:
            raise HTTPException(status_code=400, detail="No draft to approve")

    now = datetime.now(timezone.utc).isoformat()
    gmail_client.send_reply(email["thread_id"], email["sender"], email["subject"], draft["body"])

    with database.get_conn() as conn:
        conn.execute("UPDATE emails SET status = 'sent' WHERE id = ?", (email_id,))
        conn.execute(
            "UPDATE drafts SET approved_by = ?, approved_at = ?, sent_at = ? WHERE email_id = ?",
            (req.approved_by, now, now, email_id),
        )
    return {"ok": True}


class RejectRequest(BaseModel):
    note: Optional[str] = None


@app.post("/emails/{email_id}/reject")
def reject_email(email_id: int, req: RejectRequest = RejectRequest()):
    with database.get_conn() as conn:
        email = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
        if not email:
            raise HTTPException(status_code=404, detail="Email not found")
        conn.execute("UPDATE emails SET status = 'rejected' WHERE id = ?", (email_id,))
    return {"ok": True}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
