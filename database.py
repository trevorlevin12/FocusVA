import sqlite3
from contextlib import contextmanager

_db_path = "./focusva.db"


def set_db_path(path: str) -> None:
    global _db_path
    _db_path = path


@contextmanager
def get_conn():
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gmail_message_id TEXT UNIQUE,
                thread_id TEXT DEFAULT '',
                sender TEXT DEFAULT '',
                subject TEXT DEFAULT '',
                body TEXT DEFAULT '',
                received_at TEXT DEFAULT '',
                classification TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                processed_at TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS job_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_id INTEGER NOT NULL REFERENCES emails(id),
                data TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_id INTEGER NOT NULL REFERENCES emails(id),
                body TEXT DEFAULT '',
                approved_by TEXT DEFAULT '',
                approved_at TEXT DEFAULT '',
                sent_at TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS job_types (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT DEFAULT '',
                created_at TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS job_type_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_type_id INTEGER NOT NULL REFERENCES job_types(id) ON DELETE CASCADE,
                field_name TEXT NOT NULL,
                question_text TEXT NOT NULL,
                required INTEGER DEFAULT 1,
                sort_order INTEGER DEFAULT 0
            );
        """)
        _seed_job_types(conn)


def _seed_job_types(conn) -> None:
    """Insert default job types if none exist yet."""
    existing = conn.execute("SELECT COUNT(*) FROM job_types").fetchone()[0]
    if existing > 0:
        return

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    job_types = [
        ("Vinyl Banners", "Printed vinyl banners for indoor or outdoor use"),
        ("Foam Board Signs", "Rigid foam board signs and displays"),
        ("Window Graphics", "Vinyl graphics applied to glass surfaces"),
        ("Vehicle Graphics", "Wraps and decals for vehicles"),
        ("ADA Signs", "Compliant ADA signage with Braille"),
        ("Event Signage", "Trade show, conference, and event display materials"),
        ("Mesh Banners", "Perforated mesh vinyl for outdoor/wind-exposed use"),
    ]

    questions = {
        "Vinyl Banners": [
            ("width_height", "What are the dimensions? (width x height, e.g. 4ft x 8ft)", 1),
            ("quantity", "How many banners do you need?", 1),
            ("sides", "Single-sided or double-sided?", 1),
            ("grommets", "Do you need grommets? If so, every 2ft on all sides or custom spacing?", 1),
            ("hem_tape", "Hemmed edges on all sides?", 0),
            ("wind_slits", "Wind slits needed? (for outdoor banners)", 0),
            ("indoor_outdoor", "Will this be used indoors or outdoors?", 1),
            ("deadline", "What is your deadline or install date?", 1),
            ("delivery_address", "What is the delivery address?", 1),
            ("artwork_ready", "Do you have print-ready artwork? (300 DPI, CMYK, with bleed)", 1),
        ],
        "Foam Board Signs": [
            ("width_height", "What are the dimensions? (width x height)", 1),
            ("quantity", "How many signs do you need?", 1),
            ("thickness", "What thickness foam board? (3/16\" standard, 1/2\" heavy duty)", 0),
            ("sides", "Single-sided or double-sided?", 1),
            ("finish", "What finish? (matte, gloss, or UV coating)", 0),
            ("mounting", "How will these be displayed? (easels, wall-mounted, free-standing)", 1),
            ("deadline", "What is your deadline or event date?", 1),
            ("delivery_address", "What is the delivery address?", 1),
            ("artwork_ready", "Do you have print-ready artwork? (300 DPI, CMYK, with bleed)", 1),
        ],
        "Window Graphics": [
            ("window_dimensions", "What are the window dimensions? (width x height per window)", 1),
            ("quantity", "How many windows?", 1),
            ("mount_side", "Inside or outside mount?", 1),
            ("vinyl_type", "Solid vinyl or perforated one-way vision?", 1),
            ("removable", "Permanent or removable installation?", 1),
            ("deadline", "What is your deadline or install date?", 1),
            ("location_address", "What is the installation address?", 1),
            ("installation", "Do you need installation included?", 1),
            ("artwork_ready", "Do you have print-ready artwork? (300 DPI, CMYK, with bleed)", 1),
        ],
        "Vehicle Graphics": [
            ("vehicle_details", "What is the year, make, and model of the vehicle?", 1),
            ("num_vehicles", "How many vehicles?", 1),
            ("wrap_type", "Full wrap, partial wrap, or decals only?", 1),
            ("windows", "Should windows be included?", 0),
            ("installation", "Do you need installation? Will you bring the vehicle to us or need mobile install?", 1),
            ("deadline", "What is your deadline?", 1),
            ("artwork_ready", "Do you have print-ready artwork, or do you need design services?", 1),
        ],
        "ADA Signs": [
            ("sign_list", "Please provide the list of room names/numbers for each sign.", 1),
            ("quantity", "How many signs total?", 1),
            ("size", "Standard ADA sizes or custom dimensions?", 0),
            ("braille", "Braille required on all signs?", 1),
            ("mounting_hardware", "Do you need mounting hardware included?", 0),
            ("installation", "Do you need installation?", 1),
            ("deadline", "What is your deadline?", 1),
            ("delivery_address", "What is the delivery/installation address?", 1),
        ],
        "Event Signage": [
            ("sign_types", "What types of signage do you need? (banners, foam boards, retractable stands, table throws, etc.)", 1),
            ("dimensions", "What are the dimensions for each piece?", 1),
            ("quantities", "What are the quantities for each piece?", 1),
            ("event_date", "What is your event date?", 1),
            ("delivery_address", "What is the delivery address?", 1),
            ("installation", "Do you need installation and/or strike (teardown)?", 1),
            ("artwork_ready", "Do you have print-ready artwork for all pieces? (300 DPI, CMYK, with bleed)", 1),
        ],
        "Mesh Banners": [
            ("width_height", "What are the dimensions? (width x height)", 1),
            ("quantity", "How many banners?", 1),
            ("grommets", "Grommet placement? (every 2ft on all sides is standard)", 1),
            ("weld_type", "1\" weld or 2\" weld on edges?", 0),
            ("application", "What is the application? (fence wrap, building wrap, barricade, etc.)", 1),
            ("indoor_outdoor", "Indoor or outdoor use? Expected duration?", 1),
            ("deadline", "What is your deadline or install date?", 1),
            ("delivery_address", "What is the delivery address?", 1),
            ("artwork_ready", "Do you have print-ready artwork? (300 DPI, CMYK, with bleed)", 1),
        ],
    }

    for name, description in job_types:
        conn.execute(
            "INSERT INTO job_types (name, description, created_at) VALUES (?, ?, ?)",
            (name, description, now),
        )
        job_type_id = conn.execute(
            "SELECT id FROM job_types WHERE name = ?", (name,)
        ).fetchone()[0]

        for order, (field_name, question_text, required) in enumerate(questions[name]):
            conn.execute(
                """INSERT INTO job_type_questions
                   (job_type_id, field_name, question_text, required, sort_order)
                   VALUES (?, ?, ?, ?, ?)""",
                (job_type_id, field_name, question_text, required, order),
            )
