import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qr_database.db")


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
    """Return a set of all QR numbers currently marked as 'unfilled'."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT qr_number FROM unfilled_records WHERE status = 'unfilled'")
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

        cursor.execute("SELECT COUNT(*) FROM unfilled_records WHERE status = 'unfilled'")
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
        cursor.execute("""
            INSERT INTO verification_records (
                qr_number, qr_label, accuracy, status, website_data,
                image_data, field_scores, discrepancies, ai_note, image_url, ocr_raw_text, verified_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(qr_number) DO UPDATE SET
                qr_label = excluded.qr_label,
                accuracy = excluded.accuracy,
                status = excluded.status,
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


def get_verification_records(filter_status: str = "", search: str = "", limit: int = None, offset: int = 0) -> list:
    """Fetch verification records with optional status filter, search query, and pagination."""
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
        query = f"SELECT * FROM verification_records {where_sql} ORDER BY qr_number ASC"

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
    """Fetch a single verification record by QR number."""
    init_db()
    import json
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM verification_records WHERE qr_number = ?", (qr_number,))
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        for field in ["website_data", "image_data", "field_scores", "discrepancies"]:
            try:
                d[field] = json.loads(d[field])
            except Exception:
                pass
        return d


def update_verification_status(qr_number: int, status: str) -> bool:
    """Updates the status of a verification record ('resolved', 'blocked')."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE verification_records SET status = ? WHERE qr_number = ?", (status.lower(), qr_number))
        conn.commit()
        return cursor.rowcount > 0


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
            "flagged_qrs": flagged_qrs
        }



if __name__ == "__main__":
    import sys
    init_db()
    if len(sys.argv) > 2 and sys.argv[1] == "--delete":
        delete_qr_record(int(sys.argv[2]))
    else:
        last = get_last_qr_number()
        print(f"[DB Status] Last completed QR: {last}")
        print(f"[DB Status] Next QR to process: {get_next_qr_to_process()}")
        list_records()

