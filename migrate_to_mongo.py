import sqlite3
import pymongo
from datetime import datetime, timezone

SQLITE_PATH = "qr_database.db"
MONGO_URI = "mongodb+srv://official4basha_db_user:xui37tp9xiymeCTf@cluster0.ymalimp.mongodb.net/"
DB_NAME = "AI_Automation_Forms"

def migrate():
    print(f"Connecting to MongoDB {DB_NAME}...")
    client = pymongo.MongoClient(MONGO_URI)
    db = client[DB_NAME]

    print(f"Connecting to SQLite {SQLITE_PATH}...")
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 1. Fetch verification records map for enrichment
    cur.execute("SELECT * FROM verification_records")
    verif_map = {}
    for r in cur.fetchall():
        verif_map[r["qr_number"]] = dict(r)

    # 2. Fetch admin verified set
    cur.execute("SELECT qr_number, verified_at FROM admin_verified_qrs")
    admin_map = {}
    for r in cur.fetchall():
        admin_map[r["qr_number"]] = r["verified_at"]

    # 3. Migrate qr_records
    cur.execute("SELECT * FROM qr_records ORDER BY qr_number ASC")
    qr_rows = cur.fetchall()
    print(f"Found {len(qr_rows)} qr_records in SQLite.")

    qr_docs = []
    for r in qr_rows:
        num = r["qr_number"]
        v_info = verif_map.get(num, {})
        is_admin_v = num in admin_map

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
            "updated_by": None,
            "updated_at": r["updated_at"],
            "created_at": r["created_at"],
            # Enriched metadata from verification_records
            "accuracy": v_info.get("accuracy"),
            "image_url": v_info.get("image_url"),
            "ocr_raw_text": v_info.get("ocr_raw_text"),
            "discrepancies": v_info.get("discrepancies"),
            "pending_fill": False,
            "version": 1
        }
        qr_docs.append(doc)

    if qr_docs:
        coll = db["qr_forms"]
        coll.create_index([("qr_number", pymongo.ASCENDING)], unique=True)
        coll.create_index([("status", pymongo.ASCENDING)])
        coll.create_index([("verification_status", pymongo.ASCENDING)])

        # Upsert all
        ops = [
            pymongo.UpdateOne({"qr_number": d["qr_number"]}, {"$set": d}, upsert=True)
            for d in qr_docs
        ]
        res = coll.bulk_write(ops)
        print(f"qr_forms: upserted={len(res.upserted_ids)}, matched={res.matched_count}, modified={res.modified_count}")

    # 4. Migrate unfilled records
    cur.execute("SELECT * FROM unfilled_records")
    unfilled_rows = cur.fetchall()
    print(f"Found {len(unfilled_rows)} unfilled_records in SQLite.")
    unfilled_docs = []
    for r in unfilled_rows:
        unfilled_docs.append({
            "qr_number": r["qr_number"],
            "qr_label": r["qr_label"],
            "reason": r["reason"],
            "missing_fields": r["missing_fields"],
            "raw_data": r["raw_data"],
            "status": r["status"] or "unfilled",
            "created_at": r["created_at"],
            "updated_at": r["updated_at"]
        })

    if unfilled_docs:
        u_coll = db["unfilled_forms"]
        u_coll.create_index([("qr_number", pymongo.ASCENDING)], unique=True)
        ops = [
            pymongo.UpdateOne({"qr_number": d["qr_number"]}, {"$set": d}, upsert=True)
            for d in unfilled_docs
        ]
        u_res = u_coll.bulk_write(ops)
        print(f"unfilled_forms: upserted={len(u_res.upserted_ids)}, matched={u_res.matched_count}")

    # 5. Create default admin user / auth tokens collection
    tokens_coll = db["access_tokens"]
    tokens_coll.create_index([("token", pymongo.ASCENDING)], unique=True)
    tokens_coll.create_index([("user_name", pymongo.ASCENDING)])

    # Insert a starter sample token if none exist
    if tokens_coll.count_documents({}) == 0:
        import uuid
        sample_token = {
            "token": f"TOKEN-{uuid.uuid4().hex[:12].upper()}",
            "user_name": "Reviewer_1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": "admin",
            "is_active": True,
            "last_used_at": None,
            "device_id": None
        }
        tokens_coll.insert_one(sample_token)
        print(f"Created default review token: {sample_token['token']} for {sample_token['user_name']}")

    # 6. Create form_fill_queue collection for auto-filling from updated records
    queue_coll = db["fill_queue"]
    queue_coll.create_index([("qr_number", pymongo.ASCENDING)])
    queue_coll.create_index([("status", pymongo.ASCENDING)])

    conn.close()
    client.close()
    print("Migration completed successfully!")

if __name__ == "__main__":
    migrate()

