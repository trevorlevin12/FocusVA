import asyncio
import json
import urllib.parse
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import auth
import config
import crawl
import database
import gmail_client
import pipeline
import rag


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


app = FastAPI(title="Focus Graphics VA Console", lifespan=lifespan)


async def _poll_loop() -> None:
    """Background loop: sleep first, then poll, so tests complete before first cycle."""
    while True:
        await asyncio.sleep(config.POLL_INTERVAL_SECONDS)
        if not auth.is_authenticated():
            continue
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


@app.post("/poll")
async def poll_now():
    """Trigger an immediate Gmail poll outside the background schedule."""
    if not auth.is_authenticated():
        raise HTTPException(status_code=400, detail="Gmail not connected")
    emails = gmail_client.fetch_new_emails()
    new_count = 0
    for email in emails:
        with database.get_conn() as conn:
            exists = conn.execute(
                "SELECT id FROM emails WHERE gmail_message_id = ?",
                (email["gmail_message_id"],),
            ).fetchone()
        if not exists:
            pipeline.process_email(email)
            new_count += 1
    return {"fetched": len(emails), "new": new_count}


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


@app.post("/emails/{email_id}/regenerate")
def regenerate_draft(email_id: int):
    with database.get_conn() as conn:
        email = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
        if not email:
            raise HTTPException(status_code=404, detail="Email not found")
        jd = conn.execute("SELECT data FROM job_data WHERE email_id = ?", (email_id,)).fetchone()

    job_data = json.loads(jd["data"]) if jd else {}
    new_draft = pipeline.draft_response(email["body"], job_data, email["classification"])
    if new_draft is None:
        raise HTTPException(status_code=400, detail="No draft generated for this email type")

    with database.get_conn() as conn:
        existing = conn.execute("SELECT id FROM drafts WHERE email_id = ?", (email_id,)).fetchone()
        if existing:
            conn.execute("UPDATE drafts SET body = ? WHERE email_id = ?", (new_draft, email_id))
        else:
            conn.execute("INSERT INTO drafts (email_id, body) VALUES (?, ?)", (email_id, new_draft))

    return {"ok": True, "body": new_draft}


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
    rag.index_pair(email["body"], draft["body"])
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


# ── Admin: Job Types ───────────────────────────────────────

class JobTypeCreate(BaseModel):
    name: str
    description: str = ""

class JobTypeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

class QuestionCreate(BaseModel):
    field_name: str
    question_text: str
    required: bool = True
    sort_order: int = 0

class QuestionUpdate(BaseModel):
    field_name: Optional[str] = None
    question_text: Optional[str] = None
    required: Optional[bool] = None
    sort_order: Optional[int] = None


@app.get("/admin/job-types")
def list_job_types():
    with database.get_conn() as conn:
        types = conn.execute("SELECT * FROM job_types ORDER BY name").fetchall()
        result = []
        for jt in types:
            questions = conn.execute(
                "SELECT * FROM job_type_questions WHERE job_type_id = ? ORDER BY sort_order",
                (jt["id"],),
            ).fetchall()
            result.append({**dict(jt), "questions": [dict(q) for q in questions]})
    return result


@app.post("/admin/job-types", status_code=201)
def create_job_type(body: JobTypeCreate):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with database.get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO job_types (name, description, created_at) VALUES (?, ?, ?)",
            (body.name, body.description, now),
        )
    return {"id": cursor.lastrowid, "name": body.name, "description": body.description}


@app.put("/admin/job-types/{jt_id}")
def update_job_type(jt_id: int, body: JobTypeUpdate):
    with database.get_conn() as conn:
        jt = conn.execute("SELECT id FROM job_types WHERE id = ?", (jt_id,)).fetchone()
        if not jt:
            raise HTTPException(status_code=404, detail="Job type not found")
        if body.name is not None:
            conn.execute("UPDATE job_types SET name = ? WHERE id = ?", (body.name, jt_id))
        if body.description is not None:
            conn.execute("UPDATE job_types SET description = ? WHERE id = ?", (body.description, jt_id))
    return {"ok": True}


@app.delete("/admin/job-types/{jt_id}")
def delete_job_type(jt_id: int):
    with database.get_conn() as conn:
        jt = conn.execute("SELECT id FROM job_types WHERE id = ?", (jt_id,)).fetchone()
        if not jt:
            raise HTTPException(status_code=404, detail="Job type not found")
        conn.execute("DELETE FROM job_types WHERE id = ?", (jt_id,))
    return {"ok": True}


@app.post("/admin/job-types/{jt_id}/questions", status_code=201)
def add_question(jt_id: int, body: QuestionCreate):
    with database.get_conn() as conn:
        jt = conn.execute("SELECT id FROM job_types WHERE id = ?", (jt_id,)).fetchone()
        if not jt:
            raise HTTPException(status_code=404, detail="Job type not found")
        cursor = conn.execute(
            """INSERT INTO job_type_questions
               (job_type_id, field_name, question_text, required, sort_order)
               VALUES (?, ?, ?, ?, ?)""",
            (jt_id, body.field_name, body.question_text, int(body.required), body.sort_order),
        )
    return {"id": cursor.lastrowid}


@app.put("/admin/questions/{q_id}")
def update_question(q_id: int, body: QuestionUpdate):
    with database.get_conn() as conn:
        q = conn.execute("SELECT id FROM job_type_questions WHERE id = ?", (q_id,)).fetchone()
        if not q:
            raise HTTPException(status_code=404, detail="Question not found")
        if body.field_name is not None:
            conn.execute("UPDATE job_type_questions SET field_name = ? WHERE id = ?", (body.field_name, q_id))
        if body.question_text is not None:
            conn.execute("UPDATE job_type_questions SET question_text = ? WHERE id = ?", (body.question_text, q_id))
        if body.required is not None:
            conn.execute("UPDATE job_type_questions SET required = ? WHERE id = ?", (int(body.required), q_id))
        if body.sort_order is not None:
            conn.execute("UPDATE job_type_questions SET sort_order = ? WHERE id = ?", (body.sort_order, q_id))
    return {"ok": True}


@app.delete("/admin/questions/{q_id}")
def delete_question(q_id: int):
    with database.get_conn() as conn:
        q = conn.execute("SELECT id FROM job_type_questions WHERE id = ?", (q_id,)).fetchone()
        if not q:
            raise HTTPException(status_code=404, detail="Question not found")
        conn.execute("DELETE FROM job_type_questions WHERE id = ?", (q_id,))
    return {"ok": True}


# ── Auth ────────────────────────────────────────────────────

@app.get("/auth/status")
def auth_status():
    return {"connected": auth.is_authenticated()}


@app.get("/auth/login")
def auth_login():
    from fastapi.responses import RedirectResponse
    url = auth.get_auth_url()
    return RedirectResponse(url=url, status_code=302)


@app.get("/auth/callback")
def auth_callback(code: str = "", state: str = ""):
    from fastapi.responses import RedirectResponse
    try:
        auth.exchange_code(code, state)
        return RedirectResponse(url="/", status_code=302)
    except Exception as e:
        error_msg = urllib.parse.quote(str(e), safe="")
        return RedirectResponse(url=f"/?auth_error={error_msg}", status_code=302)


# ── Crawl ────────────────────────────────────────────────────

class CrawlRequest(BaseModel):
    since_date: str  # "YYYY-MM-DD"


@app.post("/admin/crawl-history")
async def start_crawl(req: CrawlRequest):
    status_key = str(uuid.uuid4())
    asyncio.create_task(crawl.crawl_sent_emails(req.since_date, status_key))
    return {"status_key": status_key}


@app.get("/admin/crawl-status")
def crawl_status(key: str = ""):
    return crawl.get_crawl_status(key)


app.mount("/", StaticFiles(directory="static", html=True), name="static")
