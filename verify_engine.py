import os
import sys
import re
import json
import time
import difflib
import threading
import requests
import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv

import db_manager
from data_entry_automation import (
    clean_text,
    sort_boxes_2d,
    parse_fallback_regex,
    refine_extracted_data,
    preprocess_image_with_padding,
    REQUIRED_FIELDS
)

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(ENV_PATH)
PORTAL_EMAIL = (os.getenv("email") or os.getenv("PORTAL_EMAIL") or "").strip()
PORTAL_PASSWORD = (os.getenv("password") or os.getenv("PORTAL_PASSWORD") or "").strip()
GROQ_API_KEY = (os.getenv("GROQ_API_KEY") or "").strip()
OPENROUTER_API_KEY = (os.getenv("OPENROUTER_API_KEY") or "").strip()

ocr_engine = RapidOCR()


def normalize_for_ocr_tolerance(s: str) -> str:
    """Normalizes string to eliminate whitespace and punctuation variations."""
    t = str(s or "").strip().lower()
    t = re.sub(r'\s+', ' ', t)
    t = re.sub(r'\s*([,\.:;\/\-\(\)])\s*', r'\1', t)
    return t


def to_ocr_homoglyph_key(txt: str) -> str:
    """
    Transforms text into an OCR-invariant key to handle:
    - '0' (zero) vs 'o' / 'O'
    - 'I' (capital I), 'l' (lowercase L), '1' (one), '|' (pipe)
    - Repeated letters dropped by OCR (e.g. 'pilli' -> 'pili', 'Hermann' -> 'Herman')
    """
    k = txt.replace('0', 'o')
    k = re.sub(r'[1\|li]', 'l', k)
    k = re.sub(r'([a-z])\1+', r'\1', k)
    return k


def are_values_ocr_equivalent(val1: str, val2: str, field_name: str = "") -> bool:
    """
    Evaluates whether two field values match identically or are equivalent under
    common optical OCR misrecognitions (casing, I/l/1 ambiguity, 0/O, and dropped repeated letters like pili vs pilli).
    """
    s1 = str(val1 or "").strip()
    s2 = str(val2 or "").strip()
    if not s1 and not s2:
        return True
    if not s1 or not s2:
        return False
    # 1. Exact match
    if s1 == s2:
        return True
    # 2. Case-insensitive exact match
    if s1.lower() == s2.lower():
        return True

    # 3. URL tolerance (trailing slashes, optional http/https/www if domain matches)
    if field_name == "website":
        u1 = re.sub(r'^https?://', '', s1.lower()).rstrip('/')
        u2 = re.sub(r'^https?://', '', s2.lower()).rstrip('/')
        if u1 == u2 or u1.replace('www.', '') == u2.replace('www.', ''):
            return True

    # 4. Office contact phone digits tolerance
    if field_name == "office_contact":
        d1 = re.sub(r'\D', '', s1)
        d2 = re.sub(r'\D', '', s2)
        if d1 and d2 and d1 == d2:
            return True

    # 5. Whitespace and punctuation normalization
    n1 = normalize_for_ocr_tolerance(s1)
    n2 = normalize_for_ocr_tolerance(s2)
    if n1 == n2:
        return True

    # 6. OCR Homoglyphs and double-letter tolerance (e.g. pilli vs pili, CIO vs ClO, 4051 vs 4o51)
    if to_ocr_homoglyph_key(n1) == to_ocr_homoglyph_key(n2):
        return True

    return False


def compute_string_similarity(val1: str, val2: str, field_name: str = "") -> float:
    """
    Computes percentage similarity (0.0 to 100.0) between two strings.
    If values are OCR-equivalent or case-variants, returns 100.0% without false penalties.
    """
    if are_values_ocr_equivalent(val1, val2, field_name):
        return 100.0

    s1 = str(val1 or "").strip()
    s2 = str(val2 or "").strip()
    if not s1 or not s2:
        return 0.0

    ratio = difflib.SequenceMatcher(None, s1, s2).ratio()
    return round(ratio * 100.0, 1)


def extract_fields_with_ai(raw_ocr_text: str) -> dict:
    """
    Uses AI LLM (Groq / OpenRouter) from .env to parse raw OCR into exact, clean 7 fields,
    actively correcting optical OCR artifacts (e.g., dropped repeated letters like 'pili' -> 'pilli',
    'I' vs 'l' vs '1', '0' vs 'O', and casing errors).
    """
    if not GROQ_API_KEY and not OPENROUTER_API_KEY:
        data = parse_fallback_regex(raw_ocr_text)
        return refine_extracted_data(data, raw_ocr_text)

    system_instruction = (
        "You are an expert, meticulous AI verification assistant for business card data extraction.\n"
        "Your task is to extract exactly 7 fields verbatim from the OCR text of a business card.\n"
        "IMPORTANT OCR CORRECTIONS:\n"
        "- Optical OCR can make errors such as dropping doubled letters (e.g., 'pili' instead of 'pilli', 'Herman' instead of 'Hermann'). Correct these obvious dropped letters.\n"
        "- Do not confuse capital 'I' (eye) with lowercase 'l' (el), digit '1', or pipe '|'. (e.g. 'CIO' not 'ClO', '10th' not 'Ioth').\n"
        "- Do not confuse '0' (zero) with 'O' (capital O) or 'o' (e.g. '4051' not '4o51', 'Obispo' not '0bispo').\n"
        "- Preserve proper casing for names, company names, cities, and addresses (e.g. 'West' not 'west', 'USA' not 'uSA').\n"
        "- Website: Keep the exact website URL without inventing protocols if absent.\n"
        "- Office Contact: Capture ALL phone/mobile numbers together. Never drop any phone number.\n"
        "Return STRICT valid JSON with exactly these 7 keys:\n"
        '{"name": "...", "designation": "...", "company": "...", "website": "...", "address": "...", "email": "...", "office_contact": "..."}'
    )

    user_prompt = f"Raw Business Card OCR Text:\n{raw_ocr_text}\n\nExtract and correct all 7 fields into valid JSON."

    # 1. Try Groq
    if GROQ_API_KEY:
        groq_models = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]
        for model in groq_models:
            try:
                res = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_instruction},
                            {"role": "user", "content": user_prompt}
                        ],
                        "response_format": {"type": "json_object"},
                        "temperature": 0.0
                    },
                    timeout=8
                )
                if res.status_code == 200:
                    data = json.loads(res.json()["choices"][0]["message"]["content"])
                    if all(k in data for k in ["name", "designation", "company"]):
                        return data
            except Exception:
                pass

    # 2. Try OpenRouter
    if OPENROUTER_API_KEY:
        openrouter_models = [
            "meta-llama/llama-3.3-70b-instruct",
            "google/gemma-4-26b-a4b-it:free"
        ]
        for model in openrouter_models:
            try:
                res = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_instruction},
                            {"role": "user", "content": user_prompt}
                        ],
                        "response_format": {"type": "json_object"},
                        "temperature": 0.0
                    },
                    timeout=10
                )
                if res.status_code == 200:
                    data = json.loads(res.json()["choices"][0]["message"]["content"])
                    if all(k in data for k in ["name", "designation", "company"]):
                        return data
            except Exception:
                pass

    # Fallback: Python regex parser
    data = parse_fallback_regex(raw_ocr_text)
    return refine_extracted_data(data, raw_ocr_text)


def extract_card_fields_from_image(image_bytes: bytes) -> tuple[dict, str]:
    """
    Directly extracts all 7 fields and full OCR text from image bytes
    using 3-Pass RapidOCR + Natural 2D reading order sort + AI LLM normalization.
    """
    nparr = np.frombuffer(image_bytes, np.uint8)
    img_cv = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    ocr_candidates = []
    # 1. Raw image
    try:
        raw_res, _ = ocr_engine(img_cv if img_cv is not None else image_bytes)
        if raw_res:
            ocr_candidates.append(('Raw', raw_res))
    except Exception:
        pass

    # 2. Padded image
    try:
        if img_cv is not None:
            padded_cv = cv2.copyMakeBorder(img_cv, 25, 25, 25, 25, cv2.BORDER_CONSTANT, value=[255, 255, 255])
            pad_res, _ = ocr_engine(padded_cv)
        else:
            pad_bytes = preprocess_image_with_padding(image_bytes, border_px=25)
            pad_res, _ = ocr_engine(pad_bytes)
        if pad_res:
            ocr_candidates.append(('Padded', pad_res))
    except Exception:
        pass

    # 3. Otsu binarization
    try:
        if img_cv is not None:
            gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
            _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            otsu_res, _ = ocr_engine(otsu)
            if otsu_res:
                ocr_candidates.append(('Otsu', otsu_res))
    except Exception:
        pass

    if not ocr_candidates:
        return {}, ""

    best_candidate = max(ocr_candidates, key=lambda c: sum(len(item[1].strip()) for item in c[1]))
    sorted_res = sort_boxes_2d(best_candidate[1])
    raw_lines = [item[1].strip() for item in sorted_res if item[1].strip()]
    full_text = clean_text(" ".join(raw_lines))

    # Parse with AI LLM from .env (with fallback to deterministic rules)
    data = extract_fields_with_ai(full_text)
    data = refine_extracted_data(data, full_text)
    return data, full_text


class VerificationEngine:
    """
    Autonomous engine that connects to the portal, downloads submitted form data & source images,
    computes verbatim accuracy, and records verification metrics.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.is_running = False
        self.cancel_requested = False
        self.status = {
            "running": False,
            "current_qr": 0,
            "current_label": "",
            "total": 0,
            "processed": 0,
            "percent": 0.0,
            "message": "Idle",
            "last_verified": None,
            "errors": []
        }

    def get_status(self) -> dict:
        with self.lock:
            return dict(self.status)

    def stop(self):
        with self.lock:
            if self.is_running:
                self.cancel_requested = True
                self.status["message"] = "Cancelling verification..."

    def start_verification_async(self, start_qr: int = 1, end_qr: int = None):
        """Spawns verification in a background worker thread."""
        with self.lock:
            if self.is_running:
                return False, "Verification already running."
            self.is_running = True
            self.cancel_requested = False
            self.status["running"] = True
            self.status["message"] = "Starting verification worker..."
            self.status["processed"] = 0
            self.status["percent"] = 0.0

        thread = threading.Thread(
            target=self._run_verification_job,
            args=(start_qr, end_qr),
            daemon=True
        )
        thread.start()
        return True, "Verification started in background."

    def _run_verification_job(self, start_qr: int = 1, end_qr: int = None):
        driver = None
        try:
            with self.lock:
                self.status["message"] = "Connecting to portal (Chrome Headless)..."

            options = webdriver.ChromeOptions()
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")
            options.add_argument("--window-size=1920,1080")

            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
            wait = WebDriverWait(driver, 25)

            # 1. Login
            driver.get("https://zendataprotsk.live/login")
            user_input = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@name='username']")))
            user_input.clear()
            user_input.send_keys(PORTAL_EMAIL)
            pwd_input = driver.find_element(By.XPATH, "//input[@name='password']")
            pwd_input.clear()
            pwd_input.send_keys(PORTAL_PASSWORD)
            driver.find_element(By.XPATH, "//form[@id='login_frm']//button[@type='submit']").click()
            time.sleep(3)

            # 2. Arrive at start-task
            driver.get("https://zendataprotsk.live/start-task")
            wait.until(EC.presence_of_element_located((By.XPATH, "//select[@id='select_data']")))
            time.sleep(1)

            # 3. Read all options from select_data
            options_els = driver.find_elements(By.XPATH, "//select[@id='select_data']/option")
            submitted_options = []

            for opt in options_els:
                text = opt.text.strip()
                val = opt.get_attribute("value")
                style = opt.get_attribute("style") or ""
                m = re.search(r'\d+', text)
                if not m or not val:
                    continue
                num = int(m.group(0))

                # Check range constraints
                if num < start_qr:
                    continue
                if end_qr is not None and num > end_qr:
                    continue

                # An option is submitted if styled lightgreen or if within range
                is_green = "lightgreen" in style.lower() or "green" in style.lower()
                submitted_options.append({
                    "qr_number": num,
                    "qr_label": text,
                    "val": val,
                    "is_green": is_green
                })

            total = len(submitted_options)
            with self.lock:
                self.status["total"] = total
                self.status["message"] = f"Found {total} QR candidates to verify."

            if total == 0:
                with self.lock:
                    self.status["message"] = "No submitted QR codes found in selected range."
                    self.status["running"] = False
                    self.is_running = False
                return

            # Batch fetch submitted data in chunks of 15 to keep it ultra fast and reliable
            chunk_size = 15
            verified_count = 0

            session = requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
            })

            for i in range(0, total, chunk_size):
                if self.cancel_requested:
                    with self.lock:
                        self.status["message"] = "Verification cancelled by user."
                    break

                chunk = submitted_options[i:i + chunk_size]
                chunk_vals = [c["val"] for c in chunk]

                # Fetch userData & image1 via browser JavaScript AJAX
                js_fetch = """
                var callback = arguments[arguments.length - 1];
                var vals = arguments[0];
                var csrf = $('meta[name="csrf-token"]').attr('content');
                var promises = vals.map(function(val) {
                    return new Promise(function(resolve) {
                        $.ajax({
                            url: "https://zendataprotsk.live/getgenerate-image",
                            type: "POST",
                            dataType: 'json',
                            data: {select_data: val},
                            headers: {'X-CSRF-TOKEN': csrf},
                            success: function(res) {
                                resolve({val: val, image1: res.image1, userData: res.userData});
                            },
                            error: function(err) {
                                resolve({val: val, image1: null, userData: null, error: String(err)});
                            }
                        });
                    });
                });
                Promise.all(promises).then(function(r) { callback(r); });
                """


                driver.set_script_timeout(30)
                batch_res = driver.execute_async_script(js_fetch, chunk_vals)
                res_map = {item["val"]: item for item in batch_res}

                # Process each item in chunk
                for item in chunk:
                    if self.cancel_requested:
                        break

                    qr_num = item["qr_number"]
                    qr_label = item["qr_label"]
                    val = item["val"]

                    with self.lock:
                        self.status["current_qr"] = qr_num
                        self.status["current_label"] = qr_label
                        self.status["message"] = f"Verifying {qr_label} ({verified_count + 1}/{total})..."

                    b_data = res_map.get(val, {})
                    image1 = b_data.get("image1")
                    user_data_raw = b_data.get("userData")

                    if not user_data_raw:
                        # QR hasn't been filled / submitted on the website yet
                        verified_count += 1
                        with self.lock:
                            self.status["processed"] = verified_count
                            self.status["percent"] = round((verified_count / total) * 100.0, 1)
                        continue

                    # Clean website data fields
                    website_data = {
                        "name": str(user_data_raw.get("name") or "").strip(),
                        "designation": str(user_data_raw.get("designation") or "").strip(),
                        "company": str(user_data_raw.get("company_name") or user_data_raw.get("company") or "").strip(),
                        "website": str(user_data_raw.get("website") or "").strip(),
                        "address": str(user_data_raw.get("address") or "").strip(),
                        "email": str(user_data_raw.get("email") or "").strip(),
                        "office_contact": str(user_data_raw.get("office_contact") or "").strip()
                    }

                    image_url = f"https://zendataprotsk.live/public/admin/data_image/{image1}" if image1 else ""

                    # Download card image
                    img_resp = session.get(image_url, timeout=12)
                    if img_resp.status_code != 200:
                        print(f"[!] Failed to download image for {qr_label}: HTTP {img_resp.status_code}")
                        verified_count += 1
                        continue

                    # Run OCR & extraction directly on image
                    image_data, raw_ocr_text = extract_card_fields_from_image(img_resp.content)

                    # Compute field scores and discrepancies
                    field_scores = {}
                    discrepancies = []

                    for f in REQUIRED_FIELDS:
                        web_val = website_data.get(f, "")
                        img_val = image_data.get(f, "")
                        score = compute_string_similarity(web_val, img_val, field_name=f)
                        field_scores[f] = score

                        if score < 100.0:
                            disc_desc = f"[{f.upper()}] Portal: '{web_val}' | Image: '{img_val}' ({score}% match)"
                            discrepancies.append(disc_desc)

                    overall_accuracy = round(sum(field_scores.values()) / len(field_scores), 1)

                    if overall_accuracy >= 100.0 or len(discrepancies) == 0:
                        overall_accuracy = 100.0
                        status = "resolved"
                        ai_note = "✅ AI Analysis: 100% Match! All fields verified with exact precision against the original card image. No discrepancies detected."
                    else:
                        status = "blocked"
                        ai_note = f"⚠️ AI Discrepancy Note: Found {len(discrepancies)} genuine mismatch: " + "; ".join(discrepancies)

                    # Save to DB
                    db_manager.save_verification_record(
                        qr_number=qr_num,
                        qr_label=qr_label,
                        accuracy=overall_accuracy,
                        status=status,
                        website_data=website_data,
                        image_data=image_data,
                        field_scores=field_scores,
                        discrepancies=discrepancies,
                        ai_note=ai_note,
                        image_url=image_url,
                        ocr_raw_text=raw_ocr_text
                    )

                    verified_count += 1
                    with self.lock:
                        self.status["processed"] = verified_count
                        self.status["percent"] = round((verified_count / total) * 100.0, 1)
                        self.status["last_verified"] = {
                            "qr_label": qr_label,
                            "accuracy": overall_accuracy,
                            "status": status
                        }

            with self.lock:
                if self.cancel_requested:
                    self.status["message"] = f"Verification stopped. Processed {verified_count} records."
                else:
                    self.status["message"] = f"Verification completed! Verified {verified_count} submitted records."
                self.status["running"] = False
                self.is_running = False

        except Exception as e:
            print(f"[!] Verification Engine error: {e}")
            with self.lock:
                self.status["errors"].append(str(e))
                self.status["message"] = f"Error during verification: {e}"
                self.status["running"] = False
                self.is_running = False
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass


# Singleton engine instance
engine_instance = VerificationEngine()


def verify_range(start_qr: int = 1, end_qr: int = None):
    """CLI runner helper."""
    engine = VerificationEngine()
    print(f"[*] Starting verification for QRCode - {start_qr} to QRCode - {end_qr or 'ALL'}...")
    engine._run_verification_job(start_qr, end_qr)
    stats = db_manager.get_verification_stats()
    print("\n" + "=" * 65)
    print("           VERIFICATION SUMMARY RESULTS")
    print("=" * 65)
    print(f"Total Verified:       {stats['total_verified']}")
    print(f"Average Accuracy:     {stats['avg_accuracy']}%")
    print(f"Perfect (100%):       {stats['perfect_count']}")
    print(f"Minor (90% - 99.9%):  {stats['minor_count']}")
    print(f"Flagged (<90%):       {stats['low_count']}")
    if stats['flagged_qrs']:
        print("\n[!] Flagged QRs requiring review:")
        for q in stats['flagged_qrs']:
            print(f"    - {q['qr_label']}: {q['accuracy']}% match")
    print("=" * 65)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Zen Data Protsk - QR Verification Engine")
    parser.add_argument("--start", type=int, default=1, help="Starting QR number (default: 1)")
    parser.add_argument("--end", type=int, default=None, help="Ending QR number (default: all submitted)")
    parser.add_argument("--qr", type=int, default=None, help="Verify a single specific QR number")
    parser.add_argument("--stats", action="store_true", help="Display verification summary statistics without re-running")
    args = parser.parse_args()

    if args.stats:
        stats = db_manager.get_verification_stats()
        print("\n" + "=" * 65)
        print("           VERIFICATION SUMMARY RESULTS")
        print("=" * 65)
        print(f"Total Verified:       {stats['total_verified']}")
        print(f"Average Accuracy:     {stats['avg_accuracy']}%")
        print(f"Perfect (100%):       {stats['perfect_count']}")
        print(f"Minor (90% - 99.9%):  {stats['minor_count']}")
        print(f"Flagged (<90%):       {stats['low_count']}")
        if stats['flagged_qrs']:
            print("\n[!] Flagged QRs requiring review:")
            for q in stats['flagged_qrs']:
                print(f"    - {q['qr_label']}: {q['accuracy']}% match")
        print("=" * 65 + "\n")
    elif args.qr is not None:
        verify_range(args.qr, args.qr)
    else:
        verify_range(args.start, args.end)

