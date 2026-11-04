import sqlite3
import os
import threading
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qr_database.db")

# Cloud MongoDB Atlas Configuration (Synced with Vercel Web App)
MONGO_URI = os.getenv(
    "MONGODB_URI",
    "mongodb+srv://official4basha_db_user:xui37tp9xiymeCTf@cluster0.ymalimp.mongodb.net/?retryWrites=true&w=majority"
)
DB_NAME = os.getenv("MONGODB_DB", "AI_Automation_Forms")

_mongo_client = None
_mongo_lock = threading.Lock()


def get_mongo_db():
    """Thread-safe lazy-initialized MongoDB client."""
    global _mongo_client
    if _mongo_client is None:
        with _mongo_lock:
            if _mongo_client is None:
                try:
                    import pymongo
                    _mongo_client = pymongo.MongoClient(
                        MONGO_URI,
                        serverSelectionTimeoutMS=3000,
                        connectTimeoutMS=3000,
                        socketTimeoutMS=5000,
                        retryWrites=True,
                    )
                except Exception:
                    return None
    try:
        return _mongo_client[DB_NAME]
    except Exception:
        return None


def _run_in_background(target_fn, *args, **kwargs):
    """Run non-blocking background thread for cloud synchronization."""
    t = threading.Thread(target=target_fn, args=args, kwargs=kwargs, daemon=True)
    t.start()
    return t


def sync_qr_record_to_mongo(qr_number: int, data: dict):
    """Synchronize a completed/updated QR record to MongoDB Atlas 'qr_forms' and resolve unfilled."""
    try:
        db = get_mongo_db()
        if db is None:
            return
        coll = db["qr_forms"]
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        doc_set = {
            "qr_number": qr_number,
            "qr_label": f"QRCode - {qr_number}",
            "name": data.get("name", "") or "",
            "designation": data.get("designation", "") or "",
            "company": data.get("company", "") or "",
            "website": data.get("website", "") or "",
            "address": data.get("address", "") or "",
            "email": data.get("email", "") or "",
            "office_contact": data.get("office_contact", "") or "",
            "status": "completed",
            "updated_at": now_str,
        }

        # Preserve existing verification status if already set in MongoDB
        coll.update_one(
            {"qr_number": qr_number},
            {
                "$set": doc_set,
                "$setOnInsert": {
                    "created_at": now_str,
                    "verification_status": "unverified",
                    "version": 1
                }
            },
            upsert=True
        )

        # Mark as resolved in unfilled_forms in MongoDB if exists
        db["unfilled_forms"].update_one(
            {"qr_number": qr_number},
            {"$set": {"status": "resolved", "updated_at": now_str}}
        )

        # Remove from fill_queue if present
        db["fill_queue"].delete_one({"qr_number": qr_number})

    except Exception:
        pass


def sync_qr_record_to_mongo_async(qr_number: int, data: dict):
    _run_in_background(sync_qr_record_to_mongo, qr_number, data)


def sync_verification_record_to_mongo(qr_number: int, accuracy: float, status: str,
                                     website_data: dict, image_data: dict, field_scores: dict,
                                     discrepancies: list, ai_note: str = "", image_url: str = "", ocr_raw_text: str = ""):
    """Synchronize a verification record to MongoDB Atlas 'qr_forms'."""
    try:
        db = get_mongo_db()
        if db is None:
            return
        coll = db["qr_forms"]
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        import json
        img_parsed = image_data if isinstance(image_data, dict) else (json.loads(image_data) if image_data else {})
        scores_parsed = field_scores if isinstance(field_scores, dict) else (json.loads(field_scores) if field_scores else {})
        disc_parsed = discrepancies if isinstance(discrepancies, (list, tuple)) else (json.loads(discrepancies) if discrepancies else [])

        update_fields = {
            "accuracy": float(accuracy) if accuracy is not None else None,
            "image_url": image_url or "",
            "ocr_raw_text": ocr_raw_text or "",
            "discrepancies": str(disc_parsed),
            "ai_note": ai_note or "",
            "image_data": img_parsed,
            "field_scores": scores_parsed,
        }

        # If admin verified locally, also reflect in verification_status
        if status == "admin_verified":
            update_fields["verification_status"] = "admin_verified"
            update_fields["verified_by"] = "admin"
            update_fields["verified_at"] = now_str

        coll.update_one(
            {"qr_number": qr_number},
            {"$set": update_fields},
            upsert=True
        )
    except Exception:
        pass


def sync_verification_record_to_mongo_async(qr_number: int, accuracy: float, status: str,
                                           website_data: dict, image_data: dict, field_scores: dict,
                                           discrepancies: list, ai_note: str = "", image_url: str = "", ocr_raw_text: str = ""):
    _run_in_background(sync_verification_record_to_mongo, qr_number, accuracy, status,
                       website_data, image_data, field_scores, discrepancies, ai_note, image_url, ocr_raw_text)


def sync_unfilled_record_to_mongo(qr_number: int, reason: str, missing_fields=None, raw_data=None, status: str = "unfilled"):
    """Synchronize an unfilled/failed record to MongoDB Atlas 'unfilled_forms'."""
    try:
        db = get_mongo_db()
        if db is None:
            return
        coll = db["unfilled_forms"]
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        missing_str = ", ".join(str(f) for f in missing_fields) if isinstance(missing_fields, (list, tuple, set)) else (str(missing_fields) if missing_fields else "")
        import json
        raw_str = json.dumps(raw_data, default=str) if isinstance(raw_data, (dict, list)) else (str(raw_data) if raw_data else "")

        coll.update_one(
            {"qr_number": qr_number},
            {
                "$set": {
                    "qr_number": qr_number,
                    "qr_label": f"QRCode - {qr_number}",
                    "reason": reason or "",
                    "missing_fields": missing_str,
                    "raw_data": raw_str,
                    "status": status,
                    "updated_at": now_str,
                },
                "$setOnInsert": {
                    "created_at": now_str,
                }
            },
            upsert=True
        )
    except Exception:
        pass


def sync_unfilled_record_to_mongo_async(qr_number: int, reason: str, missing_fields=None, raw_data=None, status: str = "unfilled"):
    _run_in_background(sync_unfilled_record_to_mongo, qr_number, reason, missing_fields, raw_data, status)



def get_connection():
    """Get a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize the database schema if it doesn't already exist."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS qr_records (
                qr_number INTEGER PRIMARY KEY,
                qr_label TEXT NOT NULL,
                name TEXT,
                designation TEXT,
                company TEXT,
                website TEXT,
                address TEXT,
                email TEXT,
                office_contact TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS unfilled_records (
                qr_number INTEGER PRIMARY KEY,
                qr_label TEXT NOT NULL,
                reason TEXT,
                missing_fields TEXT,
                raw_data TEXT,
                status TEXT DEFAULT 'unfilled',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS verification_records (
                qr_number INTEGER PRIMARY KEY,
                qr_label TEXT NOT NULL,
                accuracy REAL NOT NULL,
                status TEXT NOT NULL,
                website_data TEXT NOT NULL,
                image_data TEXT NOT NULL,
                field_scores TEXT NOT NULL,
                discrepancies TEXT NOT NULL,
                ai_note TEXT DEFAULT '',
                image_url TEXT,
                ocr_raw_text TEXT,
                verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admin_verified_qrs (
                qr_number INTEGER PRIMARY KEY,
                verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Migration for existing verification_records table
        try:
            cursor.execute("ALTER TABLE verification_records ADD COLUMN ai_note TEXT DEFAULT ''")
        except Exception:
            pass
        conn.commit()



def save_qr_record(qr_number: int, data: dict):
    """
    Save or update a QR form entry in the database.
    Also automatically resolves any entry in unfilled_records.
    """
    init_db()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO qr_records (
                qr_number, qr_label, name, designation, company,
                website, address, email, office_contact, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(qr_number) DO UPDATE SET
                qr_label = excluded.qr_label,
                name = excluded.name,
                designation = excluded.designation,
                company = excluded.company,
                website = excluded.website,
                address = excluded.address,
                email = excluded.email,
                office_contact = excluded.office_contact,
                updated_at = excluded.updated_at
        """, (
            qr_number,
            f"QRCode - {qr_number}",
            data.get("name", ""),
            data.get("designation", ""),
            data.get("company", ""),
            data.get("website", ""),
            data.get("address", ""),
            data.get("email", ""),
            data.get("office_contact", ""),
            now_str
        ))
        # If this QR was previously in unfilled_records, mark it as resolved
        cursor.execute("""
            UPDATE unfilled_records
            SET status = 'resolved', updated_at = ?
            WHERE qr_number = ?
        """, (now_str, qr_number))
        conn.commit()
    print(f"[DB] Successfully saved QRCode - {qr_number} into database.")
    # Cloud MongoDB Real-Time Sync (Non-blocking background thread)
    sync_qr_record_to_mongo_async(qr_number, data)
    # Online Brain Learning: Update local Brain model with verified record
    try:
        from brain_engine import get_brain_engine
        brain = get_brain_engine()
        raw_t = f"{data.get('name', '')} * {data.get('designation', '')} * {data.get('company', '')} * {data.get('website', '')} * {data.get('address', '')} * {data.get('email', '')} * {data.get('office_contact', '')}"
        brain.learn_single_record(qr_number, raw_t, data)
    except Exception as e:
        pass


def get_last_qr_number() -> int:
    """
    Find the last (highest) QR number recorded in the database.
    Returns 0 if the database is empty.
    """
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COALESCE(MAX(qr_number), 0) FROM qr_records")
        row = cursor.fetchone()
        return row[0] if row else 0


def get_all_completed_qrs() -> set:
    """Return a set of all completed QR numbers."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT qr_number FROM qr_records")
        return {row[0] for row in cursor.fetchall()}


def get_unverified_completed_qrs() -> list:
    """Return completed form numbers that do not have a verification record yet."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT q.qr_number
            FROM qr_records AS q
            LEFT JOIN verification_records AS v ON v.qr_number = q.qr_number
            WHERE v.qr_number IS NULL
            ORDER BY q.qr_number ASC
        """)
        return [row[0] for row in cursor.fetchall()]


def delete_qr_record(qr_number: int) -> bool:
    """
    Delete a specific QR record by its number.
    """
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM qr_records WHERE qr_number = ?", (qr_number,))
        conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            print(f"[DB] Deleted record for QRCode - {qr_number}.")
        else:
            print(f"[DB] No record found for QRCode - {qr_number}.")
        return deleted


def get_next_qr_to_process(check_missing_gaps: bool = False) -> int:
    """
    Determines the next QR number to process:
    - If check_missing_gaps is True: checks if there is any deleted QR (gap) starting from 1.
    - Otherwise (default): finds the last QR ended and returns (last_qr + 1).
    """
    init_db()
    all_qrs = get_all_completed_qrs()
    last_qr = get_last_qr_number()

    if check_missing_gaps and all_qrs:
        # Find first missing number between 1 and last_qr
        for n in range(1, last_qr + 1):
            if n not in all_qrs:
                print(f"[DB] Found missing gap: QRCode - {n} was deleted/missing.")
                return n

    # Normal mode: next after the last QR that ended
    next_qr = last_qr + 1
    return next_qr


def list_records(limit: int = 10):
    """Print the most recent records in the database."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT qr_number, qr_label, name, company, email, updated_at FROM qr_records ORDER BY qr_number DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        print(f"\n{'='*70}")
        print(f"{'QR #':<10} {'Name':<20} {'Company':<18} {'Updated At'}")
        print(f"{'='*70}")
        for r in rows:
            print(f"{r['qr_label']:<10} {r['name'][:18]:<20} {r['company'][:16]:<18} {r['updated_at']}")
        print(f"{'='*70}\n")


def save_unfilled_record(qr_number: int, reason: str, missing_fields=None, raw_data=None, status: str = "unfilled"):
    """
    Save or update an unfilled/skipped QR record with the reason and missing fields.
    """
    init_db()
    if isinstance(missing_fields, (list, tuple, set)):
        missing_str = ", ".join(str(f) for f in missing_fields)
    elif missing_fields is None:
        missing_str = ""
    else:
        missing_str = str(missing_fields)

    import json
    if isinstance(raw_data, (dict, list)):
        raw_str = json.dumps(raw_data, default=str)
    elif raw_data is None:
        raw_str = ""
    else:
        raw_str = str(raw_data)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO unfilled_records (
                qr_number, qr_label, reason, missing_fields, raw_data, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(qr_number) DO UPDATE SET
                qr_label = excluded.qr_label,
                reason = excluded.reason,
                missing_fields = excluded.missing_fields,
                raw_data = excluded.raw_data,
                status = excluded.status,
                updated_at = excluded.updated_at
        """, (
            qr_number,
            f"QRCode - {qr_number}",
            reason,
            missing_str,
            raw_str,
            status,
            now_str
        ))
        conn.commit()
    print(f"[DB] Saved QRCode - {qr_number} to Unfilled Forms. Reason: {reason}")
    # Cloud MongoDB Real-Time Sync (Non-blocking background thread)
    sync_unfilled_record_to_mongo_async(qr_number, reason, missing_fields, raw_data, status)


def mark_failure_in_db(qr_number: int, reason: str, missing_fields=None, raw_data=None, status: str = "failure_occurred_langchain_pending"):
    """
    Audit-First: Immediately record a failure occurrence in SQLite before running LangChain recovery.
    Guarantees that every failure is permanently tracked in the database.
    """
    save_unfilled_record(
        qr_number=qr_number,
        reason=reason,
        missing_fields=missing_fields,
        raw_data=raw_data,
        status=status
    )
    print(f"[DB Audit] Failure logged in DB for QRCode - {qr_number} (status='{status}'). Initiating LangChain recovery...")


def update_failure_status(qr_number: int, status: str, reason: str = None, raw_data=None):
    """Update status of a failed/unfilled record after LangChain execution."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cursor = conn.cursor()
        import json
        raw_str = json.dumps(raw_data, default=str) if isinstance(raw_data, (dict, list)) else (str(raw_data) if raw_data is not None else None)

        if reason and raw_str is not None:
            cursor.execute("""
                UPDATE unfilled_records
                SET status = ?, reason = ?, raw_data = ?, updated_at = ?
                WHERE qr_number = ?
            """, (status, reason, raw_str, now_str, qr_number))
        elif reason:
            cursor.execute("""
                UPDATE unfilled_records
                SET status = ?, reason = ?, updated_at = ?
                WHERE qr_number = ?
            """, (status, reason, now_str, qr_number))
        elif raw_str is not None:
            cursor.execute("""
                UPDATE unfilled_records
                SET status = ?, raw_data = ?, updated_at = ?
                WHERE qr_number = ?
            """, (status, raw_str, now_str, qr_number))
        else:
            cursor.execute("""
                UPDATE unfilled_records
                SET status = ?, updated_at = ?
                WHERE qr_number = ?
            """, (status, now_str, qr_number))
        conn.commit()
    # Cloud MongoDB Real-Time Sync
    sync_unfilled_record_to_mongo_async(qr_number, reason=reason or f"Status: {status}", raw_data=raw_data, status=status)


def get_unfilled_records(status_filter: str = None) -> list:
    """Fetch unfilled/skipped records, optionally filtered by status ('unfilled', 'resolved', etc.)."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        if status_filter:
            cursor.execute("""
                SELECT qr_number, qr_label, reason, missing_fields, raw_data, status, created_at, updated_at
                FROM unfilled_records
                WHERE status = ?
                ORDER BY qr_number ASC
            """, (status_filter,))
        else:
            cursor.execute("""
                SELECT qr_number, qr_label, reason, missing_fields, raw_data, status, created_at, updated_at
                FROM unfilled_records
                ORDER BY qr_number ASC
            """)
        return [dict(row) for row in cursor.fetchall()]


def get_all_unfilled_qrs() -> set:
    """Return a set of all QR numbers currently unresolved (status != 'resolved')."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT qr_number FROM unfilled_records WHERE status != 'resolved'")
        return {row[0] for row in cursor.fetchall()}


def resolve_unfilled_record(qr_number: int, status: str = "resolved") -> bool:
    """Mark an unfilled record as resolved."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            UPDATE unfilled_records
            SET status = ?, updated_at = ?
            WHERE qr_number = ?
        """, (status, now_str, qr_number))
        conn.commit()
        return cursor.rowcount > 0


def delete_unfilled_record(qr_number: int) -> bool:
    """Delete an unfilled record by QR number."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM unfilled_records WHERE qr_number = ?", (qr_number,))
        conn.commit()
        return cursor.rowcount > 0


def get_all_completed_records(search: str = "", limit: int = None, offset: int = 0) -> list:
    """Fetch all completed records with optional search across name, company, email, qr_label."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        if search:
            like_term = f"%{search}%"
            query = """
                SELECT * FROM qr_records
                WHERE qr_label LIKE ? OR name LIKE ? OR company LIKE ? OR email LIKE ? OR address LIKE ? OR office_contact LIKE ?
                ORDER BY qr_number DESC
            """
            params = [like_term, like_term, like_term, like_term, like_term, like_term]
            if limit is not None:
                query += " LIMIT ? OFFSET ?"
                params.extend([limit, offset])
            cursor.execute(query, params)
        else:
            query = "SELECT * FROM qr_records ORDER BY qr_number DESC"
            params = []
            if limit is not None:
                query += " LIMIT ? OFFSET ?"
                params.extend([limit, offset])
            cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def get_stats() -> dict:
    """Get overall statistics of completed and unfilled records."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM qr_records")
        total_completed = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM unfilled_records WHERE status != 'resolved'")
        total_unfilled = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM unfilled_records WHERE status = 'resolved'")
        total_resolved = cursor.fetchone()[0]

        last_qr = get_last_qr_number()
        next_qr = get_next_qr_to_process()

        return {
            "total_completed": total_completed,
            "total_unfilled": total_unfilled,
            "total_resolved": total_resolved,
            "last_completed_qr": last_qr,
            "next_qr": next_qr
        }


def get_unresolved_unfilled_records() -> list:
    """Fetch all unfilled/skipped records that are not resolved and not completed."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT qr_number, qr_label, reason, missing_fields, raw_data, status, created_at, updated_at
            FROM unfilled_records
            WHERE status != 'resolved'
              AND qr_number NOT IN (SELECT qr_number FROM qr_records)
            ORDER BY qr_number ASC
        """)
        return [dict(row) for row in cursor.fetchall()]



def save_verification_record(qr_number: int, qr_label: str, accuracy: float, status: str,
                             website_data: dict, image_data: dict, field_scores: dict,
                             discrepancies: list, ai_note: str = "", image_url: str = "", ocr_raw_text: str = ""):
    """Save or update a verification record in the database."""
    init_db()
    import json
    web_str = json.dumps(website_data, default=str)
    img_str = json.dumps(image_data, default=str)
    scores_str = json.dumps(field_scores, default=str)
    disc_str = json.dumps(discrepancies, default=str)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM admin_verified_qrs WHERE qr_number = ?", (qr_number,))
        if cursor.fetchone():
            status = "admin_verified"
        cursor.execute("""
            INSERT INTO verification_records (
                qr_number, qr_label, accuracy, status, website_data,
                image_data, field_scores, discrepancies, ai_note, image_url, ocr_raw_text, verified_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(qr_number) DO UPDATE SET
                qr_label = excluded.qr_label,
                accuracy = excluded.accuracy,
                status = CASE
                    WHEN verification_records.status = 'admin_verified' THEN 'admin_verified'
                    ELSE excluded.status
                END,
                website_data = excluded.website_data,
                image_data = excluded.image_data,
                field_scores = excluded.field_scores,
                discrepancies = excluded.discrepancies,
                ai_note = excluded.ai_note,
                image_url = excluded.image_url,
                ocr_raw_text = excluded.ocr_raw_text,
                verified_at = excluded.verified_at
        """, (
            qr_number, qr_label, accuracy, status, web_str,
            img_str, scores_str, disc_str, ai_note, image_url, ocr_raw_text, now_str
        ))
        conn.commit()
    # Cloud MongoDB Real-Time Sync (Non-blocking background thread)
    sync_verification_record_to_mongo_async(
        qr_number, accuracy, status, website_data, image_data,
        field_scores, discrepancies, ai_note, image_url, ocr_raw_text
    )


def get_verification_records(filter_status: str = "", search: str = "", limit: int = None, offset: int = 0) -> list:
    """Fetch verification records with optional status filter, search query, and pagination.

    Admin approvals made during the command-line data-entry flow are recorded in
    ``admin_verified_qrs`` before an OCR verification result necessarily exists.
    Include those approvals as lightweight verification records so the dashboard
    list and the "Verified by Admin" count always describe the same QR codes.
    """
    init_db()
    import json
    with get_connection() as conn:
        cursor = conn.cursor()
        clauses = []
        params = []

        if filter_status:
            clauses.append("status = ?")
            params.append(filter_status)

        if search:
            clauses.append("(qr_label LIKE ? OR website_data LIKE ? OR discrepancies LIKE ?)")
            term = f"%{search}%"
            params.extend([term, term, term])

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        query = f"""
            SELECT * FROM (
                SELECT * FROM verification_records
                UNION ALL
                SELECT
                    a.qr_number,
                    COALESCE(q.qr_label, 'QRCode - ' || a.qr_number) AS qr_label,
                    100.0 AS accuracy,
                    'admin_verified' AS status,
                    '{{}}' AS website_data,
                    '{{}}' AS image_data,
                    '{{}}' AS field_scores,
                    '[]' AS discrepancies,
                    '' AS image_url,
                    '' AS ocr_raw_text,
                    a.verified_at AS verified_at,
                    'Approved by an administrator during data entry. No separate OCR verification scan was saved.' AS ai_note
                FROM admin_verified_qrs AS a
                LEFT JOIN verification_records AS v ON v.qr_number = a.qr_number
                LEFT JOIN qr_records AS q ON q.qr_number = a.qr_number
                WHERE v.qr_number IS NULL
            ) AS verification_results
            {where_sql}
            ORDER BY qr_number ASC
        """

        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])

        cursor.execute(query, params)
        records = []
        for row in cursor.fetchall():
            d = dict(row)
            try:
                d["website_data"] = json.loads(d["website_data"])
            except Exception:
                pass
            try:
                d["image_data"] = json.loads(d["image_data"])
            except Exception:
                pass
            try:
                d["field_scores"] = json.loads(d["field_scores"])
            except Exception:
                pass
            try:
                d["discrepancies"] = json.loads(d["discrepancies"])
            except Exception:
                pass
            records.append(d)
        return records


def get_single_verification(qr_number: int) -> dict:
    """Fetch one verification record, including command-line admin approvals."""
    records = get_verification_records(filter_status="", search="")
    for record in records:
        if record["qr_number"] == qr_number:
            return record
    return None


def update_verification_status(qr_number: int, status: str) -> bool:
    """Updates the status of a verification record."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        normalized_status = status.lower()
        cursor.execute("UPDATE verification_records SET status = ? WHERE qr_number = ?", (normalized_status, qr_number))
        updated = cursor.rowcount > 0
        if normalized_status == "admin_verified":
            cursor.execute("INSERT OR REPLACE INTO admin_verified_qrs (qr_number, verified_at) VALUES (?, ?)", (qr_number, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            # A QR can be approved from the dashboard before an OCR result exists.
            # The approval marker is itself enough for it to appear in the list.
            updated = True
        elif updated:
            cursor.execute("DELETE FROM admin_verified_qrs WHERE qr_number = ?", (qr_number,))
        conn.commit()
        return updated


def mark_admin_verified(qr_number: int) -> None:
    """Persist an operator's final approval, even before a verification record exists."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("INSERT OR REPLACE INTO admin_verified_qrs (qr_number, verified_at) VALUES (?, ?)", (qr_number, now_str))
        cursor.execute("UPDATE verification_records SET status = 'admin_verified' WHERE qr_number = ?", (qr_number,))
        conn.commit()


def get_verification_stats() -> dict:
    """Calculate summary statistics for all verified records."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*), COALESCE(AVG(accuracy), 0) FROM verification_records")
        total, avg_acc = cursor.fetchone()

        cursor.execute("SELECT COUNT(*) FROM verification_records WHERE accuracy >= 100.0")
        perfect_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM verification_records WHERE accuracy >= 90.0 AND accuracy < 100.0")
        minor_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM verification_records WHERE accuracy < 90.0")
        low_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM verification_records WHERE status = 'blocked'")
        blocked_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM verification_records WHERE status = 'resolved' OR status = 'perfect'")
        resolved_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM admin_verified_qrs")
        admin_verified_count = cursor.fetchone()[0]

        cursor.execute("SELECT qr_number, qr_label, accuracy FROM verification_records WHERE status = 'blocked' OR accuracy < 90.0 ORDER BY accuracy ASC")
        flagged_qrs = [dict(r) for r in cursor.fetchall()]

        return {
            "total_verified": total,
            "avg_accuracy": round(avg_acc, 1) if total else 0.0,
            "perfect_count": perfect_count,
            "minor_count": minor_count,
            "low_count": low_count,
            "blocked_count": blocked_count,
            "resolved_count": resolved_count,
            "admin_verified_count": admin_verified_count,
            "flagged_qrs": flagged_qrs
        }


def scan_and_track_all_unfilled_qrs(max_limit: int = None, verbose: bool = True) -> dict:
    """
    Scans the entire sequence from 1 to the highest completed QR number (or max_limit).
    Detects any QRs that are missing from qr_records.
    Automatically notes and tracks them in unfilled_records and syncs with MongoDB Atlas.
    Reconciles any previously unfilled QRs that have now been completed.
    """
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT qr_number FROM qr_records")
        completed_set = {r[0] for r in cursor.fetchall()}

        max_completed = max(completed_set) if completed_set else 0
        scan_limit = max(max_completed, max_limit or 0)

        cursor.execute("SELECT qr_number, status FROM unfilled_records")
        unfilled_rows = cursor.fetchall()
        unfilled_map = {r[0]: r[1] for r in unfilled_rows}

        newly_tracked = []
        reopened = []
        resolved = []
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for n in range(1, scan_limit + 1):
            if n not in completed_set:
                # This QR is NOT completed!
                if n not in unfilled_map:
                    cursor.execute("""
                        INSERT INTO unfilled_records (qr_number, qr_label, reason, status, updated_at, created_at)
                        VALUES (?, ?, ?, 'unfilled', ?, ?)
                    """, (n, f"QRCode - {n}", "Detected missing / unfilled form during scan", now_str, now_str))
                    newly_tracked.append(n)
                elif unfilled_map[n] == "resolved":
                    cursor.execute("""
                        UPDATE unfilled_records
                        SET status = 'unfilled', reason = 'Re-opened: missing from completed records', updated_at = ?
                        WHERE qr_number = ?
                    """, (now_str, n))
                    reopened.append(n)
            else:
                # This QR IS completed!
                if n in unfilled_map and unfilled_map[n] != "resolved":
                    cursor.execute("""
                        UPDATE unfilled_records
                        SET status = 'resolved', updated_at = ?
                        WHERE qr_number = ?
                    """, (now_str, n))
                    resolved.append(n)

        conn.commit()

        # Count total unresolved
        cursor.execute("SELECT COUNT(*) FROM unfilled_records WHERE status != 'resolved'")
        total_unresolved = cursor.fetchone()[0]

    # Batch sync newly tracked to MongoDB in background
    for n in newly_tracked + reopened:
        sync_unfilled_record_to_mongo_async(n, reason="Detected missing / unfilled form during scan", status="unfilled")
    for n in resolved:
        sync_unfilled_record_to_mongo_async(n, reason="Resolved / Form completed", status="resolved")

    if verbose:
        print(f"[*] Sequence Scan (QR 1 to {scan_limit}):")
        print(f"    [+] Completed in DB:         {len(completed_set)} QRs")
        print(f"    [!] Pending Unfilled Forms:   {total_unresolved} QRs")
        if newly_tracked:
            print(f"    [+] Newly Tracked Missing:   {len(newly_tracked)} forms -> {newly_tracked[:10]}{'...' if len(newly_tracked)>10 else ''}")
        if reopened:
            print(f"    [+] Re-opened (Uncompleted): {len(reopened)} forms -> {reopened[:10]}")
        if resolved:
            print(f"    [+] Reconciled Resolved:     {len(resolved)} forms")

    return {
        "max_completed": max_completed,
        "completed_count": len(completed_set),
        "total_unresolved": total_unresolved,
        "newly_tracked": newly_tracked,
        "reopened": reopened,
        "resolved": resolved
    }


def sync_all_to_mongodb(verbose: bool = True) -> dict:
    """
    Perform a complete bulk upsert of all local SQLite records into Cloud MongoDB Atlas.
    Safe, fast, and idempotent.
    """
    try:
        import pymongo
        db = get_mongo_db()
        if db is None:
            if verbose:
                print("[MongoSync] Cloud MongoDB not reachable (Offline mode). Continuing locally.")
            return {"success": False, "error": "MongoDB unreachable"}

        init_db()
        with get_connection() as conn:
            cur = conn.cursor()

            # 1. Verification records map
            cur.execute("SELECT * FROM verification_records")
            verif_map = {r["qr_number"]: dict(r) for r in cur.fetchall()}

            # 2. Admin verified map
            cur.execute("SELECT qr_number, verified_at FROM admin_verified_qrs")
            admin_map = {r["qr_number"]: r["verified_at"] for r in cur.fetchall()}

            # 3. qr_records
            cur.execute("SELECT * FROM qr_records ORDER BY qr_number ASC")
            qr_rows = [dict(r) for r in cur.fetchall()]

            # 4. unfilled_records
            cur.execute("SELECT * FROM unfilled_records ORDER BY qr_number ASC")
            unfilled_rows = [dict(r) for r in cur.fetchall()]

        # Prepare QR forms upserts
        import json
        qr_ops = []
        for r in qr_rows:
            num = r["qr_number"]
            v_info = verif_map.get(num, {})
            is_admin_v = num in admin_map

            img_data = v_info.get("image_data")
            if isinstance(img_data, str) and img_data:
                try:
                    img_data = json.loads(img_data)
                except Exception:
                    img_data = {}
            elif not isinstance(img_data, dict):
                img_data = {}

            f_scores = v_info.get("field_scores")
            if isinstance(f_scores, str) and f_scores:
                try:
                    f_scores = json.loads(f_scores)
                except Exception:
                    f_scores = {}
            elif not isinstance(f_scores, dict):
                f_scores = {}

            doc = {
                "qr_number": num,
                "qr_label": r["qr_label"] or f"QRCode - {num}",
                "name": r["name"] or "",
                "designation": r["designation"] or "",
                "company": r["company"] or "",
                "website": r["website"] or "",
                "address": r["address"] or "",
                "email": r["email"] or "",
                "office_contact": r["office_contact"] or "",
                "status": "admin_verified" if is_admin_v else ("verified" if v_info.get("status") == "verified" else "completed"),
                "verification_status": "admin_verified" if is_admin_v else "unverified",
                "verified_by": "admin" if is_admin_v else None,
                "verified_at": admin_map.get(num) or v_info.get("verified_at"),
                "updated_at": r["updated_at"],
                "created_at": r["created_at"],
                "accuracy": v_info.get("accuracy"),
                "image_url": v_info.get("image_url") or "",
                "image_data": img_data,
                "field_scores": f_scores,
                "ocr_raw_text": v_info.get("ocr_raw_text") or "",
                "discrepancies": v_info.get("discrepancies") or "",
            }
            qr_ops.append(
                pymongo.UpdateOne(
                    {"qr_number": num},
                    {
                        "$set": doc,
                        "$setOnInsert": {"version": 1}
                    },
                    upsert=True
                )
            )

        if qr_ops:
            coll_qr = db["qr_forms"]
            coll_qr.bulk_write(qr_ops, ordered=False)

        # Prepare unfilled upserts
        unfilled_ops = []
        for u in unfilled_rows:
            num = u["qr_number"]
            unfilled_ops.append(
                pymongo.UpdateOne(
                    {"qr_number": num},
                    {
                        "$set": {
                            "qr_number": num,
                            "qr_label": u["qr_label"] or f"QRCode - {num}",
                            "reason": u["reason"] or "",
                            "missing_fields": u["missing_fields"] or "",
                            "raw_data": u["raw_data"] or "",
                            "status": u["status"] or "unfilled",
                            "updated_at": u["updated_at"],
                        },
                        "$setOnInsert": {
                            "created_at": u["created_at"]
                        }
                    },
                    upsert=True
                )
            )

        if unfilled_ops:
            coll_un = db["unfilled_forms"]
            coll_un.bulk_write(unfilled_ops, ordered=False)

        if verbose:
            print(f"[MongoSync] Cloud DB successfully synced: {len(qr_ops)} completed QRs, {len(unfilled_ops)} unfilled/tracked records.")

        return {"success": True, "synced_qrs": len(qr_ops), "synced_unfilled": len(unfilled_ops)}
    except Exception as e:
        if verbose:
            print(f"[MongoSync Warning] Cloud sync exception: {e}")
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    import sys
    init_db()
    if len(sys.argv) > 1 and sys.argv[1] == "--scan-unfilled":
        scan_and_track_all_unfilled_qrs(verbose=True)
    elif len(sys.argv) > 1 and sys.argv[1] == "--sync-mongo":
        sync_all_to_mongodb(verbose=True)
    elif len(sys.argv) > 2 and sys.argv[1] == "--delete":
        delete_qr_record(int(sys.argv[2]))
    else:
        last = get_last_qr_number()
        print(f"[DB Status] Last completed QR: {last}")
        print(f"[DB Status] Next QR to process: {get_next_qr_to_process()}")
        list_records()


