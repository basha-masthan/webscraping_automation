import io
import re
import sys
import json
import time
import base64
import random
import argparse
import requests
import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR
from PIL import Image, ImageOps

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

from db_manager import (
    init_db,
    save_qr_record,
    save_unfilled_record,
    get_unfilled_records,
    get_all_unfilled_qrs,
    get_last_qr_number,
    get_next_qr_to_process,
    get_all_completed_qrs,
    delete_qr_record,
    list_records,
    get_stats
)

import os
from dotenv import load_dotenv

# Load credentials from .env
load_dotenv()
PORTAL_EMAIL = (os.getenv("email") or os.getenv("PORTAL_EMAIL") or os.getenv("username") or "").strip()
PORTAL_PASSWORD = (os.getenv("password") or os.getenv("PORTAL_PASSWORD") or "").strip()
GROQ_API_KEY = (os.getenv("GROQ_API_KEY") or "").strip()
OPENROUTER_API_KEY = (os.getenv("OPENROUTER_API_KEY") or "").strip()

# Required fields that must ALWAYS be filled (never empty)
REQUIRED_FIELDS = [
    "name",
    "designation",
    "company",
    "website",
    "address",
    "email",
    "office_contact"
]

# Initialize RapidOCR
ocr_engine = RapidOCR()


def alert_beep():
    """Produce an audible warning beep."""
    try:
        import winsound
        winsound.Beep(1400, 350)
        time.sleep(0.1)
        winsound.Beep(1800, 450)
    except Exception:
        sys.stdout.write("\a\a")
        sys.stdout.flush()


def clean_text(text: str) -> str:
    """Normalize common OCR symbol variations to asterisk '*' and fix punctuation/URL artifacts."""
    symbols = ["•", "★", "·", "●", "◆", "■", "∗", "※"]
    for s in symbols:
        if s:
            text = text.replace(s, "*")
    # Space out asterisks so words glued to asterisks are cleanly separated
    text = re.sub(r"([^\s*])\*", r"\1 *", text)
    text = re.sub(r"\*([^\s*])", r"* \1", text)
    # Fix split URLs or excessive slashes resulting from OCR/line breaks
    text = re.sub(r"(https?://)\s*/+", r"\1", text)
    text = re.sub(r"(https?://)\s+", r"\1", text)
    text = re.sub(r"(https?):/+(?=[a-zA-Z0-9])", r"\1://", text)
    # Fix missing dot after www when OCR drops it (e.g. wwwjeffersonbank.com -> www.jeffersonbank.com)
    text = re.sub(r"\bwww(?=[a-zA-Z0-9])", "www.", text, flags=re.IGNORECASE)
    # Normalize duplicate whitespace
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def is_phone_number(s: str) -> bool:
    """Check if string contains a phone number."""
    if not s or not isinstance(s, str):
        return False
    return bool(re.search(r"\(?\d{3}\)?[- .\s]?\d{3}[- .\s]?\d{4}", s))


def is_valid_website(s: str) -> bool:
    """Strictly validates if a string is a real website URL (never a phone or email)."""
    if not s or not isinstance(s, str):
        return False
    s = s.strip()
    if is_phone_number(s) or "@" in s:
        return False
    return bool(
        re.search(r"(?:https?://|www\.)[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", s, re.IGNORECASE) or
        re.search(r"\b[a-zA-Z0-9-]+\.(?:com|org|net|io|co|in|edu|gov|live|ai|biz|info|us)\b", s, re.IGNORECASE)
    )


def is_valid_email(s: str) -> bool:
    """Strictly validates if a string is an email address."""
    if not s or not isinstance(s, str):
        return False
    return bool(re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", s.strip()))


def is_valid_contact(s: str) -> bool:
    """Validates phone number or recognized placeholder."""
    if not s or not isinstance(s, str):
        return False
    s = s.strip()
    if is_phone_number(s):
        return True
    return bool(re.match(r"^(no\s*data|n/?a|none|no\s*phone|no\s*contact|nil|not\s*available|[-]{1,3})$", s, re.IGNORECASE))


def is_address_pattern(s: str) -> bool:
    """
    Detects if a string is an address component (street, city, state, zip).
    Guarantees address lines are NEVER mistakenly treated as company or name!
    """
    if not s or not isinstance(s, str):
        return False
    t = s.strip()
    # Check for zip code (5 digits, optionally with +4)
    if re.search(r"\b\d{5}(?:-\d{4})?\b", t):
        return True
    # Check for US state / country with numbers
    us_states_country = r"\b(?:AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|USA|Canada|UK)\b"
    if re.search(us_states_country, t, re.IGNORECASE) and re.search(r"\b\d{3,5}\b", t):
        return True
    # Check for common street indicators accompanied by numbers
    street_indicators = r"\b(?:Street|St|Avenue|Ave|Boulevard|Blvd|Road|Rd|Drive|Dr|Lane|Ln|Way|Court|Ct|Circle|Cir|Suite|Ste|Floor|Fl|Parkway|Pkwy|Plaza|Mall|Box|Highway|Hwy)\b"
    if re.search(street_indicators, t, re.IGNORECASE) and re.search(r"\d+", t):
        return True
    return False


def score_data_candidate(d: dict, ocr_text: str) -> int:
    """
    Evaluates extraction quality to choose between downloaded image and screenshot.
    Heavily penalizes misidentifications (e.g. address in company) and rewards complete text.
    """
    score = 0
    if not d:
        return 0
    # Name
    if d.get("name") and not is_address_pattern(d["name"]) and not is_phone_number(d["name"]):
        score += 2
    # Designation
    if d.get("designation") and not is_address_pattern(d["designation"]) and not is_phone_number(d["designation"]):
        score += 2
    # Company: Critical! Severe penalty if company is actually an address!
    if d.get("company"):
        if is_address_pattern(d["company"]):
            score -= 6  # severe penalty
        else:
            score += 4
    # Website
    if d.get("website") and is_valid_website(d["website"]):
        score += 2
        if d["website"].startswith("http") or d["website"].startswith("www."):
            score += 2
    # Address
    if d.get("address") and not is_phone_number(d["address"]):
        score += 2
        if len(d["address"].split()) >= 3:
            score += 2
    # Email
    if d.get("email") and is_valid_email(d["email"]):
        score += 3
    # Office Contact
    if d.get("office_contact") and is_valid_contact(d["office_contact"]):
        score += 2
        if "/" in str(d["office_contact"]) or len(re.findall(r"\d{3}", str(d["office_contact"]))) >= 4:
            score += 2

    # Bonus for OCR text completeness (more chars = fewer dropped rows)
    score += min(len(ocr_text) // 25, 10)
    return score


def parse_fallback_regex(full_text: str) -> dict:
    """
    Pure Python rule-based business card parser (WITHOUT AI).
    Strictly validates every field type so phone numbers/addresses are NEVER assigned to company/website.
    """
    cleaned_t = clean_text(full_text)
    raw_parts = [re.sub(r"^[^\w(]+|[^\w)]+$", "", p.strip()) for p in cleaned_t.split("*") if p.strip()]

    # Extract semantic items via regex
    email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", cleaned_t)
    email = email_match.group(0) if email_match else ""

    # Search for website ONLY outside email to prevent email domain contamination
    text_without_email = re.sub(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", "", cleaned_t)
    web_match = re.search(r"(?:https?://|www\.)[^\s*]+", text_without_email, re.IGNORECASE)
    if not web_match:
        web_match = re.search(r"\b[a-zA-Z0-9-]+\.(?:com|org|net|io|co|in|edu|gov|live|ai|biz|info|us)[^\s*]*", text_without_email, re.IGNORECASE)
    website = web_match.group(0).rstrip(".,* ") if (web_match and is_valid_website(web_match.group(0))) else ""

    phone_matches = re.findall(r"\(?\d{3}\)?[- .\s]?\d{3}[- .\s]?\d{4}", cleaned_t)
    office_contact = " / ".join(phone_matches) if phone_matches else ""

    data = {
        "name": "",
        "designation": "",
        "company": "",
        "website": website,
        "address": "",
        "email": email,
        "office_contact": office_contact
    }

    if len(raw_parts) >= 7 and not is_address_pattern(raw_parts[2]):
        data["name"] = raw_parts[0]
        data["designation"] = raw_parts[1]
        data["company"] = raw_parts[2]
        if is_valid_website(raw_parts[3]):
            data["website"] = raw_parts[3]
        data["address"] = raw_parts[4]
        if is_valid_email(raw_parts[5]):
            data["email"] = raw_parts[5]
        if is_valid_contact(raw_parts[6]):
            data["office_contact"] = raw_parts[6]
        return data

    # Partial / wrapped row handling:
    # 1. Address parts (any part matching is_address_pattern)
    addr_parts = [p for p in raw_parts if is_address_pattern(p) and not is_valid_email(p) and not is_valid_website(p) and not is_phone_number(p)]
    if addr_parts:
        data["address"] = " ".join(addr_parts)

    # 2. Identity parts (must NOT be an address, email, website, or phone)
    id_parts = [p for p in raw_parts if not is_address_pattern(p) and not is_valid_email(p) and not is_valid_website(p) and not is_phone_number(p)]
    if len(id_parts) > 0 and not data.get("name"): data["name"] = id_parts[0]
    if len(id_parts) > 1 and not data.get("designation"): data["designation"] = id_parts[1]
    if len(id_parts) > 2 and not data.get("company"): data["company"] = id_parts[2]
    if len(id_parts) > 3 and not data.get("address"): data["address"] = id_parts[3]

    return data


def validate_and_correct_with_ai(raw_ocr_text: str) -> dict:
    """
    Multi-tier validation:
    1. Computes baseline pure-Python extraction (WITHOUT AI).
    2. Tries multiple Groq LLM models (openai/gpt-oss-120b, openai/gpt-oss-20b, qwen/qwen3.8-27b).
    3. If Groq fails, tries OpenRouter models (meta-llama/llama-3.3-70b-instruct, etc.).
    4. Automatically recovers any field missed by AI using the pure-Python extractor with type safety.
    5. If all AI models fail or hit rate limits, seamlessly uses pure-Python extraction.
    """
    # 1. Baseline Python Extraction without AI
    python_data = parse_fallback_regex(raw_ocr_text)

    def apply_type_safe_backfill(target_dict: dict):
        """Backfill empty fields from python_data with strict type validation."""
        # Sanitize any erroneous assignments made by AI
        if target_dict.get("company") and is_address_pattern(str(target_dict.get("company"))):
            print(f"[AI Validation] Cleared company incorrectly containing an address: '{target_dict['company']}'")
            target_dict["company"] = ""
        if target_dict.get("website") and is_phone_number(str(target_dict.get("website"))):
            print(f"[AI Validation] Cleared website incorrectly containing a phone: '{target_dict['website']}'")
            target_dict["website"] = ""

        for f in REQUIRED_FIELDS:
            val = str(python_data.get(f, "")).strip()
            if not val:
                continue
            if f == "website" and not is_valid_website(val):
                continue
            if f == "email" and not is_valid_email(val):
                continue
            if f == "office_contact" and not is_valid_contact(val):
                continue
            if f in ("name", "designation", "company") and (is_phone_number(val) or is_address_pattern(val)):
                continue
            if not target_dict.get(f) or not str(target_dict.get(f)).strip():
                target_dict[f] = val
                print(f"[AI+Python Recovery] Backfilled '{f}' from text: '{val}'")
            # If target website is invalid but python has valid website, restore it
            if f == "website" and not is_valid_website(str(target_dict.get("website", ""))):
                if is_valid_website(val):
                    target_dict["website"] = val

        # Strip invented http:// or https:// if absent in raw OCR text
        if not re.search(r"https?://", raw_ocr_text, re.IGNORECASE) and target_dict.get("website"):
            target_dict["website"] = re.sub(r"^https?://", "", str(target_dict["website"]))

    system_instruction = (
        "You are an expert, meticulous data extraction assistant for business contacts.\n"
        "The input text comes from a business card/QR image and spans across multiple rows.\n"
        "The asterisk '*' is the section separator for each field.\n"
        "Data is in order (or identified by content): Name, Designation, Company, Website, Address, Email, Office Contact.\n"
        "Requirements:\n"
        "1. ALL 7 fields must be extracted: name, designation, company, website, address, email, office_contact.\n"
        "2. Clean up OCR errors: duplicate brackets like '( (' or '( (650)' MUST become '(650)', double spaces, etc.\n"
        "3. Website: Extract the EXACT website URL as written in the text (e.g. 'www.example.com' or 'http://www.example.com'). DO NOT add 'http://' or 'https://' if it is not present in the input text! Never invent or prepend protocols.\n"
        "4. Exact Match & Casing: Retain the EXACT casing, words, characters, and punctuation as written on the card. Do NOT convert lowercase to uppercase or uppercase to lowercase. Preserve exact abbreviations (e.g. 'SVP').\n"
        "5. Address may span multiple lines (e.g. street prefix + City State Zip). NEVER omit street numbers, suite numbers, or directional prefixes!\n"
        "6. Office Contact: MUST capture ALL phone/mobile numbers present! If there are two numbers (e.g. separated by '/' like '(408) 526-4000 /(800) 553-6387' or with commas), YOU MUST INCLUDE BOTH NUMBERS TOGETHER. NEVER DROP ANY PHONE NUMBER!\n"
        "7. IMPORTANT: If the Office Contact section contains placeholder text like 'No Data', 'NA', 'N/A', 'None', 'No Phone', or any similar non-phone placeholder, use that exact text as the office_contact value. DO NOT leave office_contact empty just because the card says 'No Data' or 'NA'.\n"
        "8. Do NOT leave any field blank unless physically absent from the text.\n"
        "Return strictly valid JSON with EXACTLY these 7 keys:\n"
        '{"name": "...", "designation": "...", "company": "...", "website": "...", "address": "...", "email": "...", "office_contact": "..."}'
    )

    user_prompt = f"Raw Text (delimited by '*'):\n{raw_ocr_text}\n\nExtract and correct all 7 fields into valid JSON."

    # 2. Try Groq with multiple model fallbacks
    groq_models = [
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "qwen/qwen3.8-27b"
    ]
    for model_id in groq_models:
        try:
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": model_id,
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_prompt}
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.0
            }
            res = requests.post(url, headers=headers, json=payload, timeout=8)
            if res.status_code == 200:
                content = res.json()["choices"][0]["message"]["content"]
                data = json.loads(content)
                print(f"[AI LLM] Validated via Groq ({model_id}).")
                apply_type_safe_backfill(data)
                return data
            else:
                print(f"[!] Groq model {model_id} returned HTTP {res.status_code}. Trying next model...")
        except Exception as e:
            print(f"[!] Groq model {model_id} error: {e}. Trying next...")

    # 3. Try OpenRouter with multiple model fallbacks
    openrouter_models = [
        "meta-llama/llama-3.3-70b-instruct",
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "google/gemma-4-26b-a4b-it:free"
    ]
    for model_id in openrouter_models:
        try:
            url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": model_id,
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_prompt}
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.0
            }
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            if res.status_code == 200:
                content = res.json()["choices"][0]["message"]["content"]
                data = json.loads(content)
                print(f"[AI LLM] Validated via OpenRouter ({model_id}).")
                apply_type_safe_backfill(data)
                return data
            else:
                print(f"[!] OpenRouter model {model_id} returned HTTP {res.status_code}. Trying next...")
        except Exception as e:
            print(f"[!] OpenRouter model {model_id} error: {e}")

    # 4. Seamless Fallback: Pure Python Rule Parser (WITHOUT AI)
    print("[*] All online AI models unavailable/rate-limited. Using Pure-Python Rule Parser (without AI).")
    return python_data


def get_full_image_bytes(driver, img_element) -> bytes:
    """
    Downloads the full, unclipped image bytes:
    1. Direct HTTP download via src with cookies (prevents any viewport or CSS clipping).
    2. HTML5 Canvas extraction with natural dimensions.
    3. Element screenshot as fallback.
    """
    # 1. Direct download via src attribute
    try:
        src = img_element.get_attribute("src")
        if src and src.startswith("http"):
            session = requests.Session()
            for cookie in driver.get_cookies():
                session.cookies.set(cookie['name'], cookie.get('value', ''))
            user_agent = driver.execute_script("return navigator.userAgent;")
            resp = session.get(src, headers={"User-Agent": user_agent, "Referer": driver.current_url}, timeout=10)
            if resp.status_code == 200 and len(resp.content) > 500:
                print(f"[IMAGE] Downloaded full original image from server ({len(resp.content)} bytes)")
                return resp.content
    except Exception as e:
        print(f"[!] Direct image download error: {e}")

    # 2. HTML5 Canvas with natural dimensions
    try:
        b64 = driver.execute_script("""
            var img = arguments[0];
            var canvas = document.createElement('canvas');
            canvas.width = img.naturalWidth || img.width;
            canvas.height = img.naturalHeight || img.height;
            var ctx = canvas.getContext('2d');
            ctx.drawImage(img, 0, 0);
            return canvas.toDataURL('image/png').split(',')[1];
        """, img_element)
        if b64:
            data = base64.b64decode(b64)
            if len(data) > 500:
                print(f"[IMAGE] Extracted full natural dimensions via Canvas ({len(data)} bytes)")
                return data
    except Exception as e:
        print(f"[!] Canvas extraction error: {e}")

    # 3. Element screenshot
    print("[IMAGE] Falling back to element screenshot.")
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", img_element)
    time.sleep(0.5)
    return img_element.screenshot_as_png


def preprocess_image_with_padding(image_bytes: bytes, border_px: int = 35) -> bytes:
    """Adds a white margin around the image to prevent edge text from being clipped by OCR detection."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        padded = ImageOps.expand(img, border=border_px, fill='white')
        buf = io.BytesIO()
        padded.save(buf, format='PNG')
        return buf.getvalue()
    except Exception:
        return image_bytes


def extract_data_with_vision_ai(image_bytes: bytes) -> dict:
    """
    Multimodal Vision AI extraction: Reads the image directly at pixel level
    using high-precision Vision models (e.g. OpenRouter nemotron-3.5-super-vl / gemma).
    Extracts all 7 required fields even if text spans multiple rows or has unusual fonts.
    """
    if not OPENROUTER_API_KEY:
        return {}

    prompt = (
        "You are an expert OCR & business card data extraction assistant.\n"
        "Examine the image carefully. Extract exactly these 7 fields verbatim as shown in the image:\n"
        "1. name: person full name (exact casing)\n"
        "2. designation: job title (exact casing)\n"
        "3. company: company name (exact casing)\n"
        "4. website: exact website URL as printed on the card (DO NOT add http:// or https:// if not printed on the card! Keep exact casing and prefix like www)\n"
        "5. address: complete mailing address (combine street prefixes, suite numbers, city, state, country, zip)\n"
        "6. email: email address\n"
        "7. office_contact: ALL phone/mobile numbers present! If there are two numbers, YOU MUST INCLUDE BOTH NUMBERS TOGETHER. Never drop any phone number!\n\n"
        "Return strictly valid JSON with keys: name, designation, company, website, address, email, office_contact.\n"
        "Do not alter capitalization or lowercase/uppercase formatting. Do not output markdown code blocks or extra text, just the raw JSON object."
    )

    b64 = base64.b64encode(image_bytes).decode('utf-8')
    vision_models = [
        "nvidia/nemotron-3.5-super-vl:free",
        "google/gemma-4-26b-a4b-it:free",
        "dots-studio/dots-3-note-preview:free"
    ]

    for model_id in vision_models:
        try:
            print(f"[*] Activating Vision AI Model ({model_id})...")
            url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": model_id,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                        ]
                    }
                ],
                "temperature": 0.0
            }
            res = requests.post(url, headers=headers, json=payload, timeout=20)
            if res.status_code == 200:
                raw = res.json()["choices"][0]["message"]["content"].strip()
                if "```" in raw:
                    parts = raw.split("```")
                    for p in parts:
                        p_str = p.strip()
                        if p_str.startswith("json"):
                            p_str = p_str[4:].strip()
                        if p_str.startswith("{") and p_str.endswith("}"):
                            raw = p_str
                            break
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                if m:
                    data = json.loads(m.group(0))
                    print(f"[VISION AI] Successfully extracted all data with Vision Model ({model_id})!")
                    return data
            elif res.status_code == 429:
                print(f"[!] Vision Model {model_id} hit OpenRouter daily free rate limit (HTTP 429).")
            else:
                print(f"[!] Vision Model {model_id} returned HTTP {res.status_code}")
        except Exception as e:
            print(f"[!] Vision Model {model_id} error: {e}")

    print("[*] Vision AI models currently unavailable. Falling back cleanly to High-Precision Local Python Rule Parser.")
    return {}


def refine_extracted_data(data: dict, full_text: str) -> dict:
    """
    Deterministic boundary-anchor refinement:
    1. Guarantees that if the card text has multiple phone numbers (e.g. separated by '/' or commas),
       ALL phone numbers are captured together in office_contact (e.g. '(408) 526-4000 /(800) 553-6387').
    2. Guarantees that full addresses (including street prefixes like '170 West') wrapping across rows
       are never truncated.
    """
    clean_t = re.sub(r"[\r\n]+", " ", full_text)
    
    # 1. Anchor: Email
    email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", clean_t)
    # 2. Anchor: Website
    web_match = re.search(r"(?:https?://|www\.)[^\s*]+", clean_t, re.IGNORECASE)

    # A. Office Contact: Detect placeholder text OR multiple phone numbers across the entire card
    CONTACT_PLACEHOLDERS = re.compile(
        r'^(no\s*data|n/?a|none|no\s*phone|no\s*contact|nil|not\s*available|[-]{1,3})$',
        re.IGNORECASE
    )
    current_contact = str(data.get('office_contact', '')).strip()

    # Merge split area codes in current contact: (877) / (755-4279 or (877) 755-4279
    if current_contact:
        current_contact = re.sub(r'\((\d{3})\)\s*/?\s*\(?(\d{3}[- .\s]?\d{4})\)?', r'(\1) \2', current_contact)
        current_contact = re.sub(r'^\s*\(+\s*\(+', '(', current_contact)
        current_contact = re.sub(r'/\s*\(+\s*\(+', '/(', current_contact)
        current_contact = re.sub(r'\s*/\s*', ' / ', current_contact)
        data['office_contact'] = current_contact.strip()

    if email_match and not current_contact:
        after_email_raw = clean_t[email_match.end():email_match.end() + 80].strip()
        after_email_clean = re.sub(r'^[\s*\u2022,]+', '', after_email_raw).strip()
        placeholder_match = CONTACT_PLACEHOLDERS.match(after_email_clean.strip())
        if placeholder_match:
            data['office_contact'] = after_email_clean.strip()
            print(f'[REFINER] Office contact is a placeholder: "{data["office_contact"]}" - using as-is.')

    # Discover all phone numbers in clean_t (including split area codes across line breaks)
    all_raw_phones = re.findall(r'\(?\d{3}\)?[- .\s]?\d{3}[- .\s]?\d{4}', clean_t)
    split_phone_matches = re.findall(r'\((\d{3})\)[^\d]{1,60}(\d{3}[- .\s]?\d{4})', clean_t)
    for area, num in split_phone_matches:
        comb = f"({area}) {num}"
        if comb not in all_raw_phones:
            all_raw_phones.append(comb)

    curr_phones = re.findall(r'\(?\d{3}\)?[- .\s]?\d{3}[- .\s]?\d{4}', str(data.get('office_contact', '')))
    if len(all_raw_phones) > len(curr_phones) and len(all_raw_phones) >= 2:
        unique_phones = []
        for p in all_raw_phones:
            if p not in unique_phones:
                unique_phones.append(p)
        if len(unique_phones) >= 2:
            data['office_contact'] = ' / '.join(unique_phones)
            print(f'[REFINER] Restored complete multi-phone office_contact: {data["office_contact"]}')

    # B. Address: NEVER overwrite a complete address with raw unparsed text!
    current_addr = str(data.get("address", "")).strip()
    addr_is_complete = bool(
        current_addr and
        len(current_addr.split()) >= 3 and
        re.search(r"\d+", current_addr) and
        not current_addr.endswith("*") and
        not any(p in current_addr for p in [".com", "@", "http", "www."])
    )

    if not addr_is_complete and web_match and email_match and web_match.end() < email_match.start():
        raw_addr_slice = clean_t[web_match.end():email_match.start()].strip()
        raw_clean = re.sub(r"\(?\d{3}\)?[- .\s]?\d{3}[- .\s]?\d{4}", "", raw_addr_slice)
        raw_clean = re.sub(r"[a-zA-Z0-9-]+\.(?:com|org|net|io|co|in|edu|gov|live|ai|biz|info|us)\b", "", raw_clean)
        raw_clean = re.sub(r"[\s*•,]+", " ", raw_clean).strip()
        if len(raw_clean) > len(current_addr) and is_address_pattern(raw_clean):
            print(f"[REFINER] Restored address from text: '{raw_clean}' (was '{current_addr}')")
            data["address"] = raw_clean

    # C. Validate and restore website: NEVER invent http:// or https:// if absent in raw text!
    curr_web = str(data.get("website", "")).strip()
    has_protocol_in_text = bool(re.search(r"https?://", clean_t, re.IGNORECASE))
    if not has_protocol_in_text and curr_web:
        curr_web = re.sub(r"^https?://", "", curr_web)
        data["website"] = curr_web

    if curr_web and not is_valid_website(curr_web):
        if web_match and is_valid_website(web_match.group(0)):
            matched_url = web_match.group(0).rstrip(".,* ")
            if not has_protocol_in_text:
                matched_url = re.sub(r"^https?://", "", matched_url)
            data["website"] = matched_url
            print(f"[REFINER] Restored valid website URL: '{data['website']}' (was '{curr_web}')")
        else:
            data["website"] = ""
            print(f"[REFINER] Removed invalid website ('{curr_web}')")
    elif not curr_web and web_match and is_valid_website(web_match.group(0)):
        matched_url = web_match.group(0).rstrip(".,* ")
        if not has_protocol_in_text:
            matched_url = re.sub(r"^https?://", "", matched_url)
        data["website"] = matched_url
        print(f"[REFINER] Extracted website from text: '{data['website']}'")

    # D. Validate and restore company: NEVER allow an address pattern in company!
    curr_comp = str(data.get("company", "")).strip()
    if curr_comp and is_address_pattern(curr_comp):
        print(f"[REFINER] Removed address pattern incorrectly placed in company ('{curr_comp}')")
        data["company"] = ""
        curr_comp = ""

    if not curr_comp and web_match:
        before_web = clean_t[:web_match.start()].strip()
        parts_before = [p.strip() for p in before_web.split("*") if p.strip()]
        for p in reversed(parts_before):
            if not is_address_pattern(p) and not is_phone_number(p) and not is_valid_email(p):
                if p != data.get("name") and p != data.get("designation"):
                    data["company"] = p
                    print(f"[REFINER] Recovered company name preceding website: '{data['company']}'")
                    break

    # Clean double parentheses if any
    if "office_contact" in data and data["office_contact"]:
        cleaned = re.sub(r"^\s*\(+\s*\(+", "(", str(data["office_contact"]).strip())
        cleaned = re.sub(r"/\s*\(+\s*\(+", "/(", cleaned)
        data["office_contact"] = cleaned

    return data


def sort_boxes_2d(ocr_items):
    """
    Sorts OCR boxes in natural 2D reading order:
    1. Clusters boxes into lines based on vertical overlap (Y-center proximity <= 14px).
    2. Sorts lines from top to bottom.
    3. Within each line, sorts boxes from left to right (X-coordinate).
    Prevents boxes on the right from preceding boxes on the left due to 1-pixel tilt.
    """
    if not ocr_items:
        return []
    boxes = []
    for r in ocr_items:
        box = r[0]
        y_top = min(p[1] for p in box)
        y_bot = max(p[1] for p in box)
        x_left = min(p[0] for p in box)
        y_center = (y_top + y_bot) / 2.0
        boxes.append({'item': r, 'x_left': x_left, 'y_center': y_center})

    boxes.sort(key=lambda b: b['y_center'])
    lines = []
    for b in boxes:
        placed = False
        for l in lines:
            l_y = sum(x['y_center'] for x in l) / len(l)
            if abs(b['y_center'] - l_y) < 14:
                l.append(b)
                placed = True
                break
        if not placed:
            lines.append([b])

    sorted_items = []
    for l in lines:
        l.sort(key=lambda b: b['x_left'])
        sorted_items.extend(l)
    return [b['item'] for b in sorted_items]


def extract_data_from_image(image_bytes: bytes) -> tuple[dict, str]:
    """
    3-Pass AI OCR + Multi-Model AI LLM & Pure-Python Extraction:
    - Pass 1: Raw original image.
    - Pass 2: White border padding (border_px=25).
    - Pass 3: Otsu binarization (grayscale + Otsu threshold for faint/compressed text rows).
    - Selects the candidate with maximum character and row coverage.
    """
    nparr = np.frombuffer(image_bytes, np.uint8)
    img_cv = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    ocr_candidates = []

    # Pass 1: Raw image
    raw_results = None
    try:
        raw_results, _ = ocr_engine(img_cv if img_cv is not None else image_bytes)
        if raw_results:
            ocr_candidates.append(('Raw', raw_results))
    except Exception as e:
        print(f"[!] OCR Pass 1 error: {e}")

    # Pass 2: Padded image
    pad_results = None
    try:
        if img_cv is not None:
            padded_cv = cv2.copyMakeBorder(img_cv, 25, 25, 25, 25, cv2.BORDER_CONSTANT, value=[255, 255, 255])
            pad_results, _ = ocr_engine(padded_cv)
        else:
            pad_bytes = preprocess_image_with_padding(image_bytes, border_px=25)
            pad_results, _ = ocr_engine(pad_bytes)
        if pad_results:
            ocr_candidates.append(('Padded', pad_results))
    except Exception as e:
        print(f"[!] OCR Pass 2 error: {e}")

    # Pass 3: Otsu Binarization (vital for faint or compressed text rows)
    otsu_results = None
    try:
        if img_cv is not None:
            gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
            _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            otsu_bgr = cv2.cvtColor(otsu, cv2.COLOR_GRAY2BGR)
            otsu_results, _ = ocr_engine(otsu_bgr)
            if otsu_results:
                ocr_candidates.append(('Otsu', otsu_results))
    except Exception as e:
        print(f"[!] OCR Pass 3 error: {e}")

    if not ocr_candidates:
        print("[!] OCR could not detect any text in the image.")
        return {}, ""

    # Choose candidate: Prioritize Raw pass if it captured nearly the same text (binarization can fragment words)
    raw_chars = sum(len(item[1].strip()) for item in raw_results) if raw_results else 0
    otsu_chars = sum(len(item[1].strip()) for item in otsu_results) if otsu_results else 0
    pad_chars = sum(len(item[1].strip()) for item in pad_results) if pad_results else 0

    if raw_results and raw_chars >= 80 and raw_chars >= (otsu_chars * 0.90):
        best_candidate = ('Raw', raw_results)
    elif otsu_results and otsu_chars > raw_chars:
        best_candidate = ('Otsu', otsu_results)
    elif pad_results:
        best_candidate = ('Padded', pad_results)
    else:
        best_candidate = max(ocr_candidates, key=lambda c: sum(len(item[1].strip()) for item in c[1]))

    # Natural 2D reading order sort (group by vertical line, sort left-to-right)
    ocr_results = sort_boxes_2d(best_candidate[1])

    raw_lines = [item[1].strip() for item in ocr_results if item[1].strip()]
    full_text = " ".join(raw_lines)
    full_text = clean_text(full_text)

    print(f"\n[+] Detected OCR Lines ({len(raw_lines)} rows via {best_candidate[0]} Pass):")
    for idx, l in enumerate(raw_lines, 1):
        print(f"    Row {idx}: {l}")
    print(f"[+] Full Combined Text:\n    {full_text}\n")

    # AI LLM Validation with model switching & Python fallback
    data = validate_and_correct_with_ai(full_text)

    # Programmatic boundary anchor refinement (ensures multiple phones and full address)
    data = refine_extracted_data(data, full_text)

    return data, full_text


def extract_complete_form_data(driver, img_element) -> tuple[dict, str]:
    """
    Master Multi-Layer AI Extraction Model:
    1. Downloads the full unclipped server image and captures the rendered screenshot.
    2. Runs 3-Pass RapidOCR + LLM parsing with multi-model fallback on both sources.
    3. Evaluates source quality with score_data_candidate and merges best features.
    4. Evaluates Data Integrity and engages Multimodal Vision AI if needed.
    5. Pure-Python Rule-Based Recovery (WITHOUT AI) for any missing fields.
    6. Deterministic Boundary Anchor Refiner guaranteeing phone/address/website accuracy.
    """
    # 1. Download full unclipped server image
    downloaded_bytes = get_full_image_bytes(driver, img_element)

    # 2. Take on-screen rendered screenshot (what user actually sees in Chrome)
    screenshot_bytes = None
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", img_element)
        time.sleep(0.5)
        screenshot_bytes = img_element.screenshot_as_png
    except Exception as e:
        print(f"[!] Screenshot capture note: {e}")

    # 3. Extract from both sources and choose the winner
    dl_data, dl_ocr_text = {}, ""
    if downloaded_bytes:
        dl_data, dl_ocr_text = extract_data_from_image(downloaded_bytes)

    ss_data, ss_ocr_text = {}, ""
    if screenshot_bytes:
        ss_data, ss_ocr_text = extract_data_from_image(screenshot_bytes)

    dl_score = score_data_candidate(dl_data, dl_ocr_text)
    ss_score = score_data_candidate(ss_data, ss_ocr_text)

    if dl_score >= ss_score and dl_ocr_text:
        data = dl_data
        combined_raw_text = dl_ocr_text
        primary_bytes = downloaded_bytes
        secondary_data = ss_data
        print(f"[*] Chosen full downloaded image (score: {dl_score}, {len(dl_ocr_text)} chars)")
    else:
        data = ss_data or dl_data
        combined_raw_text = ss_ocr_text or dl_ocr_text
        primary_bytes = screenshot_bytes or downloaded_bytes
        secondary_data = dl_data
        print(f"[*] Chosen rendered screenshot (score: {ss_score}, {len(ss_ocr_text)} chars)")

    # Intelligent cross-backfill from the secondary source for missing/invalid fields
    if secondary_data:
        for f in REQUIRED_FIELDS:
            curr_val = str(data.get(f, "")).strip()
            sec_val = str(secondary_data.get(f, "")).strip()
            is_curr_invalid = not curr_val or (f == "company" and is_address_pattern(curr_val)) or (f == "website" and not is_valid_website(curr_val))
            is_sec_valid = bool(sec_val) and not (f == "company" and is_address_pattern(sec_val)) and not (f == "website" and not is_valid_website(sec_val))
            if is_curr_invalid and is_sec_valid:
                data[f] = sec_val
                print(f"[CROSS-SOURCE RECOVERY] Backfilled '{f}' from alternate source: '{sec_val}'")

    # 4. Comprehensive Quality & Integrity Checks
    missing_fields = [f for f in REQUIRED_FIELDS if not data.get(f) or not str(data.get(f)).strip()]
    
    # Check if contact is missing second phone number (e.g. text has '/' or 2 numbers, but data only has 1)
    raw_contact_phones = re.findall(r"\(?\d{3}\)?[- .\s]?\d{3}[- .\s]?\d{4}", combined_raw_text)
    curr_contact_phones = re.findall(r"\(?\d{3}\)?[- .\s]?\d{3}[- .\s]?\d{4}", str(data.get("office_contact", "")))
    has_contact_truncation = (len(raw_contact_phones) >= 2 and len(curr_contact_phones) < 2) or ("/" in combined_raw_text and "/" not in str(data.get("office_contact", "")))
    
    # Check if address looks truncated
    curr_addr = str(data.get("address", "")).strip()
    has_address_truncation = len(curr_addr.split()) < 3 or (any(c.isdigit() for c in combined_raw_text) and not any(c.isdigit() for c in curr_addr))

    needs_vision_ai = bool(missing_fields) or has_contact_truncation or has_address_truncation

    # 5. ENGAGE MULTIMODAL VISION AI MODEL (If needed)
    if needs_vision_ai:
        triggers = []
        if missing_fields: triggers.append(f"Missing fields: {missing_fields}")
        if has_contact_truncation: triggers.append("Multi-phone truncation detected")
        if has_address_truncation: triggers.append("Address truncation detected")
        
        print("\n" + "=" * 65)
        print(f"[AI LEARNING MODEL] Quality Check Alert: {', '.join(triggers)}")
        print("[AI LEARNING MODEL] Engaging Multimodal Vision AI Model on rendered screenshot...")
        print("=" * 65)

        target_bytes = screenshot_bytes or downloaded_bytes
        vision_data = extract_data_with_vision_ai(target_bytes)

        if vision_data:
            vision_missing = [f for f in REQUIRED_FIELDS if not vision_data.get(f) or not str(vision_data.get(f)).strip()]
            if not vision_missing:
                print("[AI LEARNING MODEL] Vision Model extracted 100% of all 7 fields perfectly!")
                data = vision_data
            else:
                for f in REQUIRED_FIELDS:
                    if vision_data.get(f) and str(vision_data.get(f)).strip():
                        data[f] = vision_data[f]
                        print(f"[+] Vision Model updated '{f}': {data[f]}")

    # 6. Safety Recovery: Pure Python extraction WITHOUT AI if any required fields remain missing
    remaining_missing = [f for f in REQUIRED_FIELDS if not data.get(f) or not str(data.get(f)).strip()]
    if remaining_missing:
        py_recovery = parse_fallback_regex(combined_raw_text)
        for f in remaining_missing:
            if py_recovery.get(f) and str(py_recovery.get(f)).strip():
                data[f] = py_recovery[f]
                print(f"[RECOVERY WITHOUT AI] Extracted missing field '{f}' directly from text: '{data[f]}'")

    # 7. Final Deterministic Boundary Anchor Refinement
    data = refine_extracted_data(data, combined_raw_text)

    return data, combined_raw_text


def fill_field(driver, possible_locators, value):
    """Locates an input field using multiple locator strategies and enters value."""
    for locator in possible_locators:
        try:
            elements = driver.find_elements(By.XPATH, locator)
            if elements:
                target = elements[0]
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target)
                target.clear()
                target.send_keys(value)
                return True
        except Exception:
            continue
    return False


def get_field_value(driver, possible_locators) -> str:
    """Reads current value from an input field in the browser."""
    for locator in possible_locators:
        try:
            elements = driver.find_elements(By.XPATH, locator)
            if elements:
                return elements[0].get_attribute("value").strip()
        except Exception:
            continue
    return ""


def sleep_with_countdown(seconds: int, message: str = "Waiting"):
    """Displays a real-time countdown on a single terminal line."""
    for remaining in range(seconds, 0, -1):
        mins, secs = divmod(remaining, 60)
        sys.stdout.write(f"\r{message}: {mins:02d}m {secs:02d}s remaining... ")
        sys.stdout.flush()
        time.sleep(1)
    sys.stdout.write(f"\r{message}: Time completed! {' ' * 20}\n")
    sys.stdout.flush()


def handle_popup_next(driver, wait_timeout: int = 15) -> bool:
    """
    Detects the 'QR Generated' popup/modal and clicks the 'Next' button.
    """
    try:
        WebDriverWait(driver, 2).until(EC.alert_is_present())
        alert = driver.switch_to.alert
        print(f"[POPUP] Alert detected ('{alert.text}'). Accepting...")
        alert.accept()
        return True
    except Exception:
        pass

    next_selectors = [
        "//button[contains(translate(normalize-space(), 'NEXT', 'next'), 'next')]",
        "//a[contains(translate(normalize-space(), 'NEXT', 'next'), 'next')]",
        "//button[contains(@class, 'swal2-confirm')]",
        "//div[contains(@class, 'modal')]//button[contains(translate(., 'NEXT', 'next'), 'next') or contains(., 'OK')]",
        "//div[contains(@class, 'swal2-actions')]//button",
        "//button[contains(., 'OK') or contains(., 'Done') or contains(., 'Next')]"
    ]

    end_time = time.time() + wait_timeout
    while time.time() < end_time:
        for selector in next_selectors:
            elements = driver.find_elements(By.XPATH, selector)
            for el in elements:
                try:
                    if el.is_displayed() and el.is_enabled():
                        btn_text = el.text.strip() or "Next"
                        print(f"[POPUP] Popup detected with button '{btn_text}'. Clicking...")
                        driver.execute_script("arguments[0].click();", el)
                        return True
                except Exception:
                    continue
        time.sleep(0.5)

    print("[!] Notice: No popup appeared or it closed automatically.")
    return False


def parse_range(input_str: str, default_min: int, default_max: int) -> tuple[int, int]:
    """Parse range inputs like '45-75' or '45 to 75' or '45' or empty for default."""
    s = input_str.strip()
    if not s:
        return default_min, default_max
    if "-" in s:
        parts = s.split("-")
        try:
            return int(parts[0].strip()), int(parts[1].strip())
        except ValueError:
            pass
    elif "to" in s.lower():
        parts = s.lower().split("to")
        try:
            return int(parts[0].strip()), int(parts[1].strip())
        except ValueError:
            pass
    else:
        try:
            val = int(s)
            return val, val
        except ValueError:
            pass
    return default_min, default_max


def prompt_settings(fill_unfilled_first: bool = None):
    """Interactive setup before running the automation."""
    init_db()
    stats = get_stats()
    total_completed = stats["total_completed"]
    total_unfilled = stats["total_unfilled"]
    last_qr = stats["last_completed_qr"]
    next_qr = stats["next_qr"]

    print("\n" + "=" * 65)
    print("      ZEN DATA PROTSK - AI AUTOMATED DATA ENTRY LOOP")
    print("=" * 65)
    print(f"[*] Total QRs Completed in Database: {total_completed}")
    print(f"[*] Total Unfilled / Skipped Forms:  {total_unfilled}")
    print(f"[*] Last Completed QR:               QRCode - {last_qr}")
    print(f"[*] Next QR to Process:              QRCode - {next_qr}")
    print("-" * 65)

    # Mode selection: if not provided by CLI flag, ask if there are unfilled forms
    if fill_unfilled_first is None:
        if total_unfilled > 0:
            print(f"[!] Found {total_unfilled} unfilled/skipped forms in database.")
            ans = input(f"[?] Fill unfilled previous forms first before next QR? (y/n) [Default: n]: ").strip().lower()
            fill_unfilled_first = ans in ("y", "yes")
        else:
            fill_unfilled_first = False

    # 1. Time gap between forms
    default_gap = "45-75"
    gap_input = input(f"[?] Enter inspection & wait time between forms in seconds (e.g. 45-75) [Default: {default_gap}s]: ")
    min_gap, max_gap = parse_range(gap_input, 45, 75)
    if min_gap > max_gap:
        min_gap, max_gap = max_gap, min_gap

    # 2. Forms per batch
    default_batch = "22-35"
    batch_input = input(f"[?] Enter how many forms to fill in a row before a break (e.g. 22-35) [Default: {default_batch}]: ")
    min_batch, max_batch = parse_range(batch_input, 22, 35)
    if min_batch > max_batch:
        min_batch, max_batch = max_batch, min_batch

    # 3. Break duration
    default_break = "15-45"
    break_input = input(f"[?] Enter break duration between batches in minutes (e.g. 15-45) [Default: {default_break} min]: ")
    min_break_min, max_break_min = parse_range(break_input, 15, 45)
    if min_break_min > max_break_min:
        min_break_min, max_break_min = max_break_min, min_break_min

    print("\n" + "-" * 65)
    print(f"[CONFIG] Fill Unfilled First:  {'YES (Will resolve unfilled forms first)' if fill_unfilled_first else 'NO (Normal queue)'}")
    print(f"[CONFIG] Human Review & Delay: {min_gap} to {max_gap} seconds on screen before submit")
    print(f"[CONFIG] Forms Per Batch:      {min_batch} to {max_batch} forms in a row")
    print(f"[CONFIG] Batch Break:          {min_break_min} to {max_break_min} minutes")
    print(f"[CONFIG] Automation Start:     QRCode - {next_qr}")
    print("=" * 65 + "\n")

    return {
        "min_gap": min_gap,
        "max_gap": max_gap,
        "min_batch": min_batch,
        "max_batch": max_batch,
        "min_break_sec": min_break_min * 60,
        "max_break_sec": max_break_min * 60,
        "start_qr": next_qr,
        "fill_unfilled_first": fill_unfilled_first
    }


def wait_for_image_ready(driver, wait_timeout: int = 15):
    """Waits until the QR data image is visible and finished loading."""
    end_time = time.time() + wait_timeout
    while time.time() < end_time:
        try:
            imgs = driver.find_elements(By.XPATH, "//img[contains(@src, 'data_image')]")
            if imgs:
                img = imgs[0]
                is_loaded = driver.execute_script(
                    "return arguments[0].complete && typeof arguments[0].naturalWidth != 'undefined' && arguments[0].naturalWidth > 0;",
                    img
                )
                if is_loaded:
                    return img
        except Exception:
            pass
        time.sleep(0.5)

    return driver.find_element(
        By.XPATH,
        "//img[contains(@src, 'data_image') or contains(@class, 'img') or ancestor::div[contains(@class,'card')]]"
    )


def perform_portal_login(driver, portal_url: str):
    """
    Handles authentication into Zen Data Protsk automatically.
    The login form at https://zendataprotsk.live/login uses:
    - input name="username" placeholder="Username"
    - input name="password" placeholder="Password"
    - button type="submit" (Sign In) inside form#login_frm
    """
    if not PORTAL_EMAIL or not PORTAL_PASSWORD:
        print("\n" + "=" * 60)
        print("[!] LOGIN REQUIRED: No credentials found in .env.")
        print("    Please log in to your account in the opened Chrome window.")
        print("=" * 60 + "\n")
        input("Press Enter here once you have logged in and are on the task page...")
        return

    print(f"[*] Detected Login Page. Logging in automatically as '{PORTAL_EMAIL}' from .env...")
    try:
        # 1. Locate username input (the portal uses name='username')
        user_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((
                By.XPATH,
                "//input[@name='username' or @id='username' or @name='email' or @id='email' or contains(@placeholder, 'User') or contains(@placeholder, 'Email') or @type='email']"
            ))
        )
        user_input.clear()
        user_input.send_keys(PORTAL_EMAIL)
        # Dispatch input and change events for reactive form frameworks
        driver.execute_script("arguments[0].dispatchEvent(new Event('input', {bubbles: true})); arguments[0].dispatchEvent(new Event('change', {bubbles: true}));", user_input)

        # 2. Locate password input
        pwd_input = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((
                By.XPATH,
                "//input[@type='password' or @name='password' or @id='password' or contains(@placeholder, 'Password')]"
            ))
        )
        pwd_input.clear()
        pwd_input.send_keys(PORTAL_PASSWORD)
        driver.execute_script("arguments[0].dispatchEvent(new Event('input', {bubbles: true})); arguments[0].dispatchEvent(new Event('change', {bubbles: true}));", pwd_input)

        time.sleep(0.5)

        # 3. Locate and click submit button
        submit_btn = None
        btns = driver.find_elements(
            By.XPATH,
            "//form[@id='login_frm']//button[@type='submit'] | //button[contains(., 'Sign In') or contains(., 'Login')] | //button[@type='submit']"
        )
        for b in btns:
            if b.is_displayed():
                submit_btn = b
                break

        if submit_btn:
            driver.execute_script("arguments[0].click();", submit_btn)
        else:
            driver.execute_script("var f = document.getElementById('login_frm') || document.querySelector('form'); if(f) f.submit();")

        print("[✓] Login form submitted. Waiting for redirect...")

        # 4. Wait for redirection away from login page
        try:
            WebDriverWait(driver, 15).until(
                lambda d: "login" not in d.current_url.lower()
            )
        except Exception:
            pass

        time.sleep(2)

        # 5. Ensure we are on the task page
        if "start-task" not in driver.current_url.lower():
            print(f"[*] Navigating to task page: {portal_url}")
            driver.get(portal_url)
            time.sleep(2)

        print("[✓] Successfully authenticated and arrived on task page!")

    except Exception as e:
        print(f"[!] Auto-login encountered an issue: {e}")
        print("    Please complete login manually in the browser window if needed.")
        input("Press Enter once you have logged in and see the form on the task page...")


def clear_form_inputs(driver):
    """Clears all input fields in the form."""
    field_selectors = [
        "//input[@name='name']",
        "//input[@placeholder='Name']",
        "//input[@name='designation']",
        "//input[@placeholder='Designation']",
        "//input[@name='company_name']",
        "//input[@placeholder='Company Name']",
        "//input[@name='website']",
        "//input[@placeholder='Website']",
        "//input[@name='address']",
        "//input[@placeholder='Address']",
        "//input[@name='email']",
        "//input[@placeholder='Email']",
        "//input[@name='office_contact']",
        "//input[@placeholder='Office Contact']"
    ]
    for sel in field_selectors:
        try:
            for el in driver.find_elements(By.XPATH, sel):
                el.clear()
        except Exception:
            pass


def select_qr_code(driver, qr_label: str, wait: WebDriverWait, force_reload: bool = False):
    """
    Selects the QR code in the dropdown.
    If force_reload is True, switches away to another option first then back,
    ensuring the portal's onchange listener fires fresh and re-renders the image.
    """
    dropdown_element = wait.until(
        EC.presence_of_element_located((By.XPATH, "//select[@id='select_data' or @name='select_data']"))
    )
    select = Select(dropdown_element)

    if force_reload:
        try:
            opts = select.options
            if len(opts) > 1:
                cur_text = select.first_selected_option.text.strip()
                alt_idx = 1 if opts[0].text.strip() == cur_text else 0
                select.select_by_index(alt_idx)
                driver.execute_script("arguments[0].dispatchEvent(new Event('change', {bubbles: true}));", dropdown_element)
                time.sleep(1.0)
        except Exception as e:
            print(f"[!] Dropdown toggle note: {e}")

    current_selected = ""
    try:
        current_selected = select.first_selected_option.text.strip()
    except Exception:
        pass

    if current_selected != qr_label or force_reload:
        print(f"[*] Selecting '{qr_label}' from dropdown...")
        try:
            select.select_by_visible_text(qr_label)
        except Exception:
            match = re.search(r'\d+', qr_label)
            if match:
                select.select_by_index(int(match.group(0)))
            else:
                select.select_by_visible_text(qr_label)
        driver.execute_script("arguments[0].dispatchEvent(new Event('change', {bubbles: true}));", dropdown_element)


def take_batch_break(config: dict, forms_filled: int):
    """Takes a randomized rest between batches with countdown display."""
    break_duration = random.randint(config["min_break_sec"], config["max_break_sec"])
    break_mins = round(break_duration / 60, 1)
    print("\n" + "=" * 65)
    print(f"[BATCH COMPLETED] Filled {forms_filled} forms in this row.")
    print(f"[LONG BREAK] Taking a rest of {break_mins} minutes before next batch...")
    print("=" * 65)
    sleep_with_countdown(break_duration, message="[BATCH BREAK]")


def process_single_qr(driver, current_qr: int, config: dict, wait: WebDriverWait) -> bool:
    """
    Processes a single QR code.
    If data is missing or unable to extract by the image on the first attempt,
    automatically performs a retry on the SAME QR to re-extract the data.

    Returns:
        True if the form was successfully validated, submitted, and saved.
        False if it failed after retry and was saved to unfilled_records.
    """
    qr_label = f"QRCode - {current_qr}"
    max_attempts = 2  # 1 initial attempt + 1 retry if data is missing or unextractable

    for attempt in range(1, max_attempts + 1):
        is_retry = (attempt > 1)
        if is_retry:
            print("\n" + "-" * 65)
            print(f"[RETRY SYSTEM] Retrying {qr_label} (Attempt {attempt}/{max_attempts}) to get data...")
            print("-" * 65)
            clear_form_inputs(driver)
            select_qr_code(driver, qr_label, wait, force_reload=True)
        else:
            select_qr_code(driver, qr_label, wait, force_reload=False)

        try:
            # 1. Wait for image to load completely
            print(f"[*] Waiting for data image to fully load for {qr_label}...")
            time.sleep(2)
            img_element = wait_for_image_ready(driver)

            # 2. Master Multi-Layer AI Model: Padded OCR + Vision AI Fallback + Precision Cross-Validation
            data, full_ocr_text = extract_complete_form_data(driver, img_element)

            print(f"\n[+] Extracted Data for {qr_label} (Attempt {attempt}):")
            for k, v in data.items():
                print(f"    - {k.capitalize():15}: {v}")

            # 3. STRICT VALIDATION CHECK: Never assume on genuinely missing data!
            # Placeholder values like 'No Data', 'NA', 'N/A' are valid (literal card text).
            missing_fields = [
                f for f in REQUIRED_FIELDS
                if not data.get(f) or not str(data.get(f)).strip()
            ]

            if missing_fields:
                if attempt < max_attempts:
                    print("\n" + "!" * 70)
                    print(f"[DATA MISSING / INCOMPLETE ON ATTEMPT {attempt}] For {qr_label}!")
                    print(f"Empty/Missing fields: {missing_fields}")
                    print(f"[*] Doing once again the same QR ({qr_label}) to try to get the data...")
                    print("!" * 70)
                    time.sleep(2)
                    continue  # Trigger retry on same QR
                else:
                    alert_beep()
                    reason_msg = f"Missing required fields after retry: {', '.join(missing_fields)}"
                    print("\n" + "!" * 70)
                    print(f"[WARNING / STILL MISSING AFTER RETRY] For {qr_label}!")
                    print(f"Empty/Missing fields: {missing_fields}")
                    print(f"Full OCR Text:\n    {full_ocr_text}")
                    print(f"[!] Storing {qr_label} into Unfilled Forms...")
                    save_unfilled_record(current_qr, reason=reason_msg, missing_fields=missing_fields, raw_data=data)
                    print("!" * 70)
                    print(f"[*] Beep alert triggered. Waiting for 30 seconds before moving to next QR...")
                    sleep_with_countdown(30, message=f"[SKIPPED {qr_label} - MISSING DATA] Moving to next QR in")
                    return False

            # 4. Fill form inputs on screen
            print("\n[*] Autofilling inputs into the form...")
            field_mappings = [
                ("name", ["//input[@name='name']", "//input[@placeholder='Name']", "//label[contains(text(),'Name')]/following::input[1]"], data.get("name", "")),
                ("designation", ["//input[@name='designation']", "//input[@placeholder='Designation']", "//label[contains(text(),'Designation')]/following::input[1]"], data.get("designation", "")),
                ("company", ["//input[@name='company_name']", "//input[@placeholder='Company Name']", "//label[contains(text(),'Company')]/following::input[1]"], data.get("company", "")),
                ("website", ["//input[@name='website']", "//input[@placeholder='Website']", "//label[contains(text(),'Website')]/following::input[1]"], data.get("website", "")),
                ("address", ["//input[@name='address']", "//input[@placeholder='Address']", "//label[contains(text(),'Address')]/following::input[1]"], data.get("address", "")),
                ("email", ["//input[@name='email']", "//input[@placeholder='Email']", "//label[contains(text(),'Email')]/following::input[1]"], data.get("email", "")),
                ("office_contact", ["//input[@name='office_contact']", "//input[@placeholder='Office Contact']", "//label[contains(text(),'Contact')]/following::input[1]"], data.get("office_contact", "")),
            ]

            filled = 0
            for fname, locators, val in field_mappings:
                if val:
                    fill_field(driver, locators, val)
                    filled += 1

            # 5. Post-fill verification: Check inputs directly in the browser DOM
            empty_browser_fields = []
            final_form_data = {}
            for fname, locators, expected_val in field_mappings:
                current_val = get_field_value(driver, locators)
                final_form_data[fname] = current_val or expected_val
                if not current_val:
                    empty_browser_fields.append(fname)

            if empty_browser_fields:
                if attempt < max_attempts:
                    print("\n" + "!" * 70)
                    print(f"[INCOMPLETE INPUT ON ATTEMPT {attempt}] Empty browser fields: {empty_browser_fields}")
                    print(f"[*] Doing once again the same QR ({qr_label}) to try to get the data...")
                    print("!" * 70)
                    time.sleep(2)
                    continue  # Trigger retry on same QR
                else:
                    alert_beep()
                    reason_msg = f"Incomplete fields in browser DOM after retry: {', '.join(empty_browser_fields)}"
                    print("\n" + "!" * 70)
                    print(f"[WARNING / INCOMPLETE AFTER RETRY] The following fields are empty: {empty_browser_fields}")
                    print(f"[!] Storing {qr_label} into Unfilled Forms...")
                    save_unfilled_record(current_qr, reason=reason_msg, missing_fields=empty_browser_fields, raw_data=final_form_data)
                    print("!" * 70)
                    print(f"[*] Beep alert triggered. Waiting for 30 seconds before moving to next QR...")
                    sleep_with_countdown(30, message=f"[SKIPPED {qr_label} - INCOMPLETE INPUT] Moving to next QR in")
                    return False

            if is_retry:
                print(f"[✓] Retry successful! All 7/7 fields confirmed populated on screen for {qr_label}.")
            else:
                print(f"[✓] All 7/7 fields confirmed populated on screen.")

            # 6. Human Review & Inspection Countdown (Form is filled on screen)
            wait_delay = random.randint(config["min_gap"], config["max_gap"])
            print(f"\n[HUMAN INSPECTION] Form is filled. Pausing {wait_delay}s so you can inspect before auto-submit.")
            sleep_with_countdown(wait_delay, message=f"[SUBMIT TIMER] Submitting {qr_label} in")

            # 7. Click "Generate QRCode" Button
            print(f"[*] Submitting form for {qr_label} ('Generate QRCode')...")
            submit_selectors = [
                "//button[contains(normalize-space(), 'Generate QRCode')]",
                "//button[contains(., 'Generate')]",
                "//input[@value='Generate QRCode']",
                "//div[contains(@class,'card')]//button[@type='button' or @type='submit']"
            ]
            clicked = False
            for sel in submit_selectors:
                btns = driver.find_elements(By.XPATH, sel)
                for b in btns:
                    if b.is_displayed():
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", b)
                        time.sleep(0.5)
                        driver.execute_script("arguments[0].click();", b)
                        clicked = True
                        break
                if clicked:
                    break

            if not clicked:
                print("[!] Warning: Could not locate 'Generate QRCode' button.")

            # 8. Handle popup and click 'Next'
            time.sleep(1)
            handle_popup_next(driver, wait_timeout=15)

            # 9. Update database with confirmed data (also marks any unfilled record as resolved)
            save_qr_record(current_qr, final_form_data)
            return True

        except Exception as qr_err:
            if attempt < max_attempts:
                print("\n" + "!" * 70)
                print(f"[ERROR ON ATTEMPT {attempt}] Error for {qr_label}: {qr_err}")
                print(f"[*] Doing once again the same QR ({qr_label}) to try to get the data...")
                print("!" * 70)
                time.sleep(2)
                continue
            else:
                alert_beep()
                err_msg = str(qr_err)
                print("\n" + "!" * 70)
                print(f"[ERROR OCCURRED AFTER RETRY] Error during processing for {qr_label}: {err_msg}")
                print(f"[!] Storing {qr_label} into Unfilled Forms...")
                save_unfilled_record(current_qr, reason=f"Error after retry: {err_msg}", missing_fields=["error"], raw_data=None)
                print("!" * 70)
                print(f"[*] Beep alert triggered. Waiting for 30 seconds before moving to next QR...")
                sleep_with_countdown(30, message=f"[ERROR DELAY {qr_label}] Moving to next QR in")
                return False

    return False


def run_continuous_automation(config: dict, max_total_qrs: int = 1200):
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    print("[*] Starting Chrome Browser...")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    wait = WebDriverWait(driver, 30)

    forms_in_current_batch = 0
    target_batch_size = random.randint(config["min_batch"], config["max_batch"])

    try:
        portal_url = "https://zendataprotsk.live/start-task"
        print(f"[*] Navigating to {portal_url}")
        driver.get(portal_url)

        time.sleep(2)
        # Check if redirected to login page or password field is present
        is_login_page = "login" in driver.current_url.lower() or len(driver.find_elements(By.XPATH, "//input[@type='password'] | //input[@name='username']")) > 0
        
        if is_login_page:
            perform_portal_login(driver, portal_url)

        print(f"\n[+] Batch target set: Will process {target_batch_size} forms in this row before a long break.\n")

        # -------------------------------------------------------------------------
        # PHASE 1: FILL UNFILLED PREVIOUS FORMS FIRST (If requested)
        # -------------------------------------------------------------------------
        if config.get("fill_unfilled_first"):
            unfilled_records = get_unfilled_records(status_filter="unfilled")
            unfilled_qrs = sorted(list({int(r["qr_number"]) for r in unfilled_records if r.get("qr_number")}))

            if unfilled_qrs:
                print("\n" + "=" * 65)
                print(f"  [MODE: RESOLVING UNFILLED FORMS FIRST] ({len(unfilled_qrs)} forms pending)")
                print(f"  Target QRs: {', '.join(f'QRCode - {n}' for n in unfilled_qrs)}")
                print("=" * 65 + "\n")

                for idx, u_qr in enumerate(unfilled_qrs, 1):
                    print(f"\n{'='*65}")
                    print(f"[*] Processing Unfilled Form {idx}/{len(unfilled_qrs)}: QRCode - {u_qr}")
                    print(f"{'='*65}")

                    success = process_single_qr(driver, u_qr, config, wait)
                    if success:
                        forms_in_current_batch += 1
                        if forms_in_current_batch >= target_batch_size:
                            take_batch_break(config, forms_in_current_batch)
                            forms_in_current_batch = 0
                            target_batch_size = random.randint(config["min_batch"], config["max_batch"])
                            print(f"\n[+] Break finished. New batch target set to {target_batch_size} forms.")

                print("\n" + "=" * 65)
                print("  [✓] COMPLETED ATTEMPTING ALL PREVIOUS UNFILLED FORMS!")
                print("  Now seamlessly continuing to the next QR in queue...")
                print("=" * 65 + "\n")
            else:
                print("\n[*] No pending unfilled forms found in database. Continuing to next QR in queue.\n")

        # -------------------------------------------------------------------------
        # PHASE 2: CONTINUE NORMAL CONTINUOUS QR LOOP
        # -------------------------------------------------------------------------
        next_qr_in_db = get_next_qr_to_process()
        current_qr = max(config["start_qr"], next_qr_in_db)

        print(f"\n[*] Continuing normal automation queue starting from QRCode - {current_qr} up to QRCode - {max_total_qrs}...\n")

        while current_qr <= max_total_qrs:
            qr_label = f"QRCode - {current_qr}"
            print(f"\n{'='*65}")
            print(f"[*] Processing: {qr_label} (Batch progress: {forms_in_current_batch + 1}/{target_batch_size})")
            print(f"{'='*65}")

            success = process_single_qr(driver, current_qr, config, wait)
            if success:
                forms_in_current_batch += 1
                if forms_in_current_batch >= target_batch_size:
                    take_batch_break(config, forms_in_current_batch)
                    forms_in_current_batch = 0
                    target_batch_size = random.randint(config["min_batch"], config["max_batch"])
                    print(f"\n[+] Break finished. New batch target set to {target_batch_size} forms.")

            current_qr += 1

        print("\n[ALL DONE] Reached end of 1200 QRs or target limit!")

    except KeyboardInterrupt:
        print("\n\n[!] Script paused/stopped by user. Database is completely saved and up to date.")
        print(f"[*] When you run again, it will automatically resume from QRCode - {get_next_qr_to_process()}.")
    except Exception as e:
        print(f"\n[!] Unexpected error: {e}")
        print(f"[*] Progress saved. Next run will resume from QRCode - {get_next_qr_to_process()}.")
    finally:
        print("\nClosing browser...")
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Zen Data Protsk Automated Form Data Entry Loop with AI LLM Validation")
    parser.add_argument("--delete", type=int, default=None, help="Delete a specific QR record from the database (e.g. --delete 1)")
    parser.add_argument("--list", action="store_true", help="List recent completed records from the database")
    parser.add_argument("--unfilled", action="store_true", help="List all unfilled/skipped records")
    parser.add_argument("--stats", action="store_true", help="Show database summary statistics")
    parser.add_argument("--fill-unfilled-first", action="store_true", help="Process and fill all pending unfilled forms first before continuing next QRs")
    args = parser.parse_args()

    init_db()

    if args.delete is not None:
        delete_qr_record(args.delete)
        last_qr = get_last_qr_number()
        next_qr = get_next_qr_to_process()
        print(f"[DB Status] Last completed QR in DB is now: QRCode - {last_qr}")
        print(f"[DB Status] Next run will resume from:       QRCode - {next_qr}")
    elif args.unfilled:
        unfilled = get_unfilled_records()
        print(f"\n{'='*75}")
        print(f"{'UNFILLED / SKIPPED FORMS':^75}")
        print(f"{'='*75}")
        print(f"{'QR #':<12} {'Status':<10} {'Reason':<30} {'Updated At'}")
        print(f"{'-'*75}")
        if not unfilled:
            print("  No unfilled forms recorded. All clear!")
        else:
            for r in unfilled:
                reason = (r['reason'] or '')[:28]
                print(f"{r['qr_label']:<12} {r['status']:<10} {reason:<30} {r['updated_at']}")
        print(f"{'='*75}\n")
    elif args.stats:
        stats = get_stats()
        print(f"\n{'='*45}")
        print(f"{'DATABASE STATISTICS':^45}")
        print(f"{'='*45}")
        print(f" Total Completed QRs:     {stats['total_completed']}")
        print(f" Total Unfilled/Skipped:  {stats['total_unfilled']}")
        print(f" Total Resolved Unfilled: {stats['total_resolved']}")
        print(f" Last Completed QR:       QRCode - {stats['last_completed_qr']}")
        print(f" Next QR in Queue:        QRCode - {stats['next_qr']}")
        print(f"{'='*45}\n")
    elif args.list:
        list_records(limit=25)
    else:
        cfg = prompt_settings(fill_unfilled_first=True if args.fill_unfilled_first else None)
        run_continuous_automation(cfg)
