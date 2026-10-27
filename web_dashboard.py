import os
import sys
import json
import csv
import io
import socket
import webbrowser
import argparse
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import db_manager
import verify_engine

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")



def alert_beep():
    """Trigger system alert beep."""
    try:
        import winsound
        winsound.Beep(1400, 350)
        winsound.Beep(1800, 450)
    except Exception:
        sys.stdout.write("\a\a")
        sys.stdout.flush()


class DashboardRequestHandler(SimpleHTTPRequestHandler):
    """Handles static web dashboard assets and JSON REST APIs."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def log_message(self, format, *args):
        # Concise logging for cleaner console output
        sys.stdout.write(f"[DASHBOARD] {self.address_string()} - {args[0]} {args[1]}\n")
        sys.stdout.flush()

    def send_json(self, data, status_code=200):
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # 1. API: Stats
        if path == "/api/stats":
            stats = db_manager.get_stats()
            self.send_json(stats)
            return

        # 2. API: Completed Records with Search & Pagination
        if path == "/api/records":
            search = query.get("search", [""])[0].strip()
            page = int(query.get("page", ["1"])[0])
            limit = int(query.get("limit", ["25"])[0])
            offset = max(0, (page - 1) * limit)

            all_matching = db_manager.get_all_completed_records(search=search)
            total = len(all_matching)
            records = all_matching[offset:offset + limit]

            self.send_json({
                "records": records,
                "total": total,
                "page": page,
                "limit": limit
            })
            return

        # 3. API: Single Record Details
        if path == "/api/record":
            qr_num = int(query.get("qr", ["0"])[0])
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM qr_records WHERE qr_number = ?", (qr_num,))
                row = cursor.fetchone()
                if row:
                    self.send_json(dict(row))
                else:
                    self.send_json({"error": "Record not found"}, status_code=404)
            return

        # 4. API: Unfilled Records
        if path == "/api/unfilled":
            status_filter = query.get("status", [""])[0].strip() or None
            records = db_manager.get_unfilled_records(status_filter=status_filter)
            self.send_json({
                "records": records,
                "total": len(records)
            })
            return

        # 4b. API: Verification Results
        if path == "/api/verify/results":
            status_filter = query.get("status", [""])[0].strip()
            search = query.get("search", [""])[0].strip()
            page = int(query.get("page", ["1"])[0])
            limit = int(query.get("limit", ["25"])[0])
            offset = max(0, (page - 1) * limit)

            all_matching = db_manager.get_verification_records(filter_status=status_filter, search=search)
            total = len(all_matching)
            records = all_matching[offset:offset + limit]

            self.send_json({
                "records": records,
                "total": total,
                "page": page,
                "limit": limit
            })
            return

        # 4c. API: Verification Stats
        if path == "/api/verify/stats":
            stats = db_manager.get_verification_stats()
            self.send_json(stats)
            return

        # 4d. API: Single Verification Record
        if path == "/api/verify/record":
            qr_num = int(query.get("qr", ["0"])[0])
            rec = db_manager.get_single_verification(qr_num)
            if rec:
                self.send_json(rec)
            else:
                self.send_json({"error": "Verification record not found"}, status_code=404)
            return

        # 4e. API: Verification Live Progress
        if path == "/api/verify/progress":
            progress = verify_engine.engine_instance.get_status()
            self.send_json(progress)
            return


        # 5. API: Export Data (CSV or JSON)
        if path == "/api/export":
            export_type = query.get("type", ["completed"])[0].lower()
            export_fmt = query.get("format", ["csv"])[0].lower()

            if export_type == "unfilled":
                records = db_manager.get_unfilled_records()
                filename = "unfilled_forms"
            else:
                records = db_manager.get_all_completed_records()
                filename = "completed_qr_records"

            if export_fmt == "json":
                body = json.dumps(records, indent=2, default=str).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Disposition", f'attachment; filename="{filename}.json"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            else:
                # CSV Export
                output = io.StringIO()
                if records:
                    fieldnames = list(records[0].keys())
                    writer = csv.DictWriter(output, fieldnames=fieldnames)
                    writer.writeheader()
                    for r in records:
                        writer.writerow(r)
                csv_bytes = output.getvalue().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{filename}.csv"')
                self.send_header("Content-Length", str(len(csv_bytes)))
                self.end_headers()
                self.wfile.write(csv_bytes)
                return

        # Fallback to static files
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Read JSON body
        content_length = int(self.headers.get("Content-Length", 0))
        body_data = {}
        if content_length > 0:
            try:
                body_bytes = self.wfile if False else self.rfile.read(content_length)
                body_data = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                body_data = {}

        # 1. API: Trigger Beep
        if path == "/api/beep":
            alert_beep()
            self.send_json({"success": True})
            return

        # 2. API: Resolve Unfilled Record
        if path == "/api/unfilled/resolve":
            qr_number = body_data.get("qr_number")
            if qr_number:
                ok = db_manager.resolve_unfilled_record(int(qr_number))
                self.send_json({"success": ok})
            else:
                self.send_json({"error": "Missing qr_number"}, status_code=400)
            return

        # 3. API: Delete Unfilled Record
        if path == "/api/unfilled/delete":
            qr_number = body_data.get("qr_number")
            if qr_number:
                ok = db_manager.delete_unfilled_record(int(qr_number))
                self.send_json({"success": ok})
            else:
                self.send_json({"error": "Missing qr_number"}, status_code=400)
            return

        # 4. API: Save/Update Record (Manual entry or resolving an unfilled form)
        if path == "/api/save-record":
            qr_number = body_data.get("qr_number")
            data = body_data.get("data", {})
            if qr_number and data:
                try:
                    db_manager.save_qr_record(int(qr_number), data)
                    self.send_json({"success": True})
                except Exception as e:
                    self.send_json({"error": str(e)}, status_code=500)
            else:
                self.send_json({"error": "Missing qr_number or data"}, status_code=400)
            return

        # 5. API: Delete Completed Record
        if path == "/api/delete-record":
            qr_number = body_data.get("qr_number")
            if qr_number:
                ok = db_manager.delete_qr_record(int(qr_number))
                self.send_json({"success": ok})
            else:
                self.send_json({"error": "Missing qr_number"}, status_code=400)
            return

        # 6. API: Start Verification
        if path == "/api/verify/start":
            start_qr = int(body_data.get("start_qr", 1))
            end_qr = body_data.get("end_qr")
            if end_qr:
                end_qr = int(end_qr)
            ok, msg = verify_engine.engine_instance.start_verification_async(start_qr=start_qr, end_qr=end_qr)
            self.send_json({"success": ok, "message": msg})
            return

        # 7. API: Stop Verification
        if path == "/api/verify/stop":
            verify_engine.engine_instance.stop()
            self.send_json({"success": True, "message": "Verification stop requested."})
            return

        # 8. API: Update Verification Status (Resolved / Blocked)
        if path == "/api/verify/update-status":
            qr_number = body_data.get("qr_number")
            new_status = str(body_data.get("status", "")).strip().lower()
            if qr_number and new_status in ("resolved", "blocked"):
                ok = db_manager.update_verification_status(int(qr_number), new_status)
                self.send_json({"success": ok, "status": new_status})
            else:
                self.send_json({"error": "Invalid qr_number or status (must be 'resolved' or 'blocked')"}, status_code=400)
            return

        self.send_json({"error": "Endpoint not found"}, status_code=404)




def find_available_port(start_port=5000):
    """Find an available port starting from start_port."""
    for port in [start_port, 5001, 5050, 8080, 8888]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start_port


def run_dashboard(port=None, auto_open=True):
    db_manager.init_db()

    if port is None:
        port = find_available_port(5000)

    server_address = ("127.0.0.1", port)
    httpd = ThreadingHTTPServer(server_address, DashboardRequestHandler)
    url = f"http://localhost:{port}"

    stats = db_manager.get_stats()

    print("\n" + "=" * 65)
    print("      ZEN DATA PROTSK - WEB DASHBOARD SERVER")
    print("=" * 65)
    print(f"[*] Dashboard URL:        {url}")
    print(f"[*] Completed QR Codes:   {stats['total_completed']}")
    print(f"[*] Unfilled Forms:       {stats['total_unfilled']}")
    print(f"[*] Next QR in Queue:     QRCode - {stats['next_qr']}")
    print("=" * 65)
    print("[*] Press Ctrl+C to stop the dashboard server.\n")

    if auto_open:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] Stopping Dashboard Server...")
        httpd.server_close()
        print("[✓] Server stopped cleanly.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Zen Data Protsk Web Dashboard Server")
    parser.add_argument("--port", type=int, default=None, help="Port to run web server on (default: auto)")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open the browser")
    args = parser.parse_args()

    run_dashboard(port=args.port, auto_open=not args.no_browser)
