# Zen Data Protsk - AI Automated Data Entry with Secure .env & Auto-Login

A Python + Selenium + AI OCR + AI LLM automation tool for automatically logging in, reading text images, cross-checking and correcting errors with AI LLMs (Groq / OpenRouter), filling form fields, pausing for human review, submitting, and updating a local SQLite database for the **Zen Data Protsk** portal.

---

## 1. Secure Environment Configuration (`.env`)

Your credentials and API keys are stored securely in `.env`:
```env
email=your_email@example.com
password=your_password
GROQ_API_KEY=your_groq_api_key_here
OPENROUTER_API_KEY=your_openrouter_api_key_here
```

- When the automation opens Chrome, it **automatically logs in** using `email` and `password` from [.env](file:///c:/Users/basha/OneDrive/Documents/Desktop/Temp_Work/.env) and redirects straight to `https://zendataprotsk.live/start-task`.
- You do not need to type credentials manually anymore!

---

## 2. Key Safety & Accuracy Features

1. **Master Multi-Layer AI Extraction Architecture**:
   - **Layer 1 (Dual-Pass RapidOCR)**: Runs on both the unpadded raw image (protecting Row 1 from being dropped) and padded image, automatically selecting the pass with maximum text and row coverage.
   - **Layer 2 (Multi-Provider, Multi-Model AI Switching)**: Automatically cycles through multiple LLM models across providers (`openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.8-27b`, `meta-llama/llama-3.3-70b-instruct`, etc.) if any model errors or is rate-limited.
   - **Layer 3 (Pure Python Extraction WITHOUT AI)**: If any AI model is unavailable, rate-limited (HTTP 429), or misses a field, a deterministic pure-Python semantic rule parser extracts and backfills all 7 fields directly from the card text with 0 dependency on external AI APIs.
   - **Layer 4 (Multimodal Vision AI Fallback)**: Reads raw pixels when text is heavily obscured or complex.
   - **Layer 5 (Dual Capture - Screen CDP + Server Download)**: Captures on-screen rendered pixels alongside server downloads for full image integrity.

2. **Multi-Row & Asterisk `*` Section Separation**:
   - Handles cards spanning across **any number of rows** (1, 2, 3, or more).
   - Treats `*` as the true section separator. If an address wraps across rows (e.g. Row 2 street + Row 3 City/State/Zip), it automatically combines them into one complete address.

3. **Multi-Phone Number & Address Prefix Preservation**:
   - Automatically detects and captures **all phone numbers** (e.g. primary and toll-free numbers separated by `/` or commas, such as `(408) 526-4000 /(800) 553-6387` or `(714) 250-6400 /(949) 214-1000`). Never drops either phone number!
   - Boundary-anchor refiner guarantees that street prefixes (like `170 West`) and suite/building details wrapping across lines are fully preserved.

4. **Strict Zero-Assumption Safety Check**:
   - Validates that all 7 required fields are non-empty:
     - **Name**
     - **Designation**
     - **Company**
     - **Website**
     - **Address**
     - **Email**
      - **Office Contact**
   - **Automatic Retry on Missing Data or Image Extraction Issues**:
     - If data is missing or unable to be extracted from the image on the first pass (e.g. temporary network lag, blurred render, or empty input), the system does **not** immediately skip.
     - It **automatically retries the exact same QR code once again**: clears form inputs, re-selects the QR code in the dropdown to force the portal to fetch a fresh image, waits for image load, and re-executes AI extraction.
     - Only if the data remains genuinely unresolvable after the retry does it trigger the audible warning beep alert and record it in **Unfilled Forms**.
   - **If a QR remains unresolvable after retry:**
     - It produces an **audible warning beep alert**.
     - Automatically logs the skipped QR code number, failure reason, and missing fields into **Unfilled Forms** in the database.
     - Displays a live **30-second countdown timer** on console.
     - Automatically advances to the next QR code when the 30 seconds elapse.
     - You never lose track of skipped work — all skipped items are recorded in the **Unfilled Forms** section of the Web Dashboard and database for quick review or manual resolution!

5. **Fill Unfilled Forms First Mode**:
   - You can choose to automatically resolve all previously skipped/unfilled forms before processing new QRs.
   - Once all pending unfilled forms are attempted, the automation seamlessly resumes continuous processing from the next QR code in queue.

6. **Pre-Submit Human Review Delay**:
   - Once all 7 fields are filled on screen, displays a live countdown timer (e.g. 45 to 75 seconds).
   - Allows you to inspect the filled fields on screen.
   - When the timer reaches 0, automatically clicks **"Generate QRCode"**, clicks **"Next"** on the popup, and updates the database.

7. **Batch Rest System**:
   - After completing a batch of forms in a row (e.g. 22 to 35 forms), takes a randomized long break (e.g. 15 to 45 minutes) with a live countdown, then continues to the next batch.

---

## 3. Web Dashboard (Access Completed Work & Handle Unfilled Forms)

The application includes a built-in interactive Web Dashboard to monitor all automation progress, view generated QR records, inspect skipped/unfilled forms, and manually resolve or fill forms:

### Launching the Dashboard:
Double-click **`start_dashboard.bat`** or run:
```powershell
python web_dashboard.py
```
Then visit **`http://localhost:5000`** in any web browser.

### Features in the Web Dashboard:
1. **Generated QR Codes**:
   - Live searchable archive of all completed records (Name, Designation, Company, Email, Contact, Address).
   - Full 7-field detail inspection modal.
   - Export all completed records to CSV or JSON with 1 click.
2. **Unfilled Forms (Skipped)**:
   - Tracks all QR codes skipped due to missing data or filling errors.
   - Displays exact error reasons and highlighted missing field tags.
   - "Fill & Resolve" modal allowing you to fill missing fields manually and submit straight to the completed database.
   - Quick "Mark as Resolved" and "Export to CSV/JSON" buttons.
3. **Manual QR Entry / Edit**:
   - Fill or edit any QR number directly into the local SQLite database.
4. **Live Controls**:
   - Real-time auto-refresh (5s, 10s, 30s).
   - "Test Alert Beep" button to test audible alerts.

---

## 4. How to Run

Simply double-click **`run.bat`** (which now includes an interactive menu to start the automation, web dashboard, or both).

### Useful Management Commands
- **View all completed records in Database**:
  ```powershell
  python data_entry_automation.py --list
  ```
- **View all unfilled/skipped forms**:
  ```powershell
  python data_entry_automation.py --unfilled
  ```
- **View database summary statistics**:
  ```powershell
  python data_entry_automation.py --stats
  ```
- **Fill Unfilled Forms First, Then Continue**:
  ```powershell
  python data_entry_automation.py --fill-unfilled-first
  ```
- **Delete a QR record from Database**:
  ```powershell
  python data_entry_automation.py --delete 5
  ```

---

## 5. Verification & Ground-Truth Cross-Check (`verify_run.bat`)

You can verify all submitted forms directly against their original source card images without relying on any internal database:

- **Launch Interactive Verification Menu**:
  Double-click [verify_run.bat](file:///c:/Users/basha/OneDrive/Documents/Desktop/Temp_Work/verify_run.bat)
- **Verify All Submitted QRs**:
  ```powershell
  verify_run.bat
  ```
- **Verify a Custom Range (e.g. QRs 1 to 50)**:
  ```powershell
  verify_run.bat 1 50
  ```
- **Verify a Single QR Code (e.g. QRCode - 153)**:
  ```powershell
  verify_run.bat 153
  ```
- **View Verification Results on Web Dashboard**:
  Open `http://localhost:5000` and click the **Verify Submissions** tab.

#
