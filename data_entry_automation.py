import io
import re
import sys
import json
import time
import difflib

try:
    import msvcrt  # Windows-only non-blocking console input for the review timer.
except ImportError:
    msvcrt = None

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
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
    mark_failure_in_db,
    update_failure_status,
    get_unfilled_records,
    get_all_unfilled_qrs,
    get_last_qr_number,
    get_next_qr_to_process,
    get_all_completed_qrs,
    get_unverified_completed_qrs,
    mark_admin_verified,
    delete_qr_record,
    list_records,
    get_stats
)
from langchain_extractor import extract_with_langchain_ensemble

import os
from dotenv import load_dotenv

# Load credentials from .env
load_dotenv()
PORTAL_EMAIL = (os.getenv("email") or os.getenv("PORTAL_EMAIL") or os.getenv("username") or "").strip()
PORTAL_PASSWORD = (os.getenv("password") or os.getenv("PORTAL_PASSWORD") or "").strip()
GROQ_API_KEY = (os.getenv("GROQ_API_KEY") or "").strip()
OPENROUTER_API_KEY = (os.getenv("OPENROUTER_API_KEY") or "").strip()

# LLM wrappers for OpenRouter and Groq (used in post‑processing)
from functools import lru_cache
import requests

class OpenRouterLLM:
    def __init__(self, api_key: str, model: str = "nvidia/nemotron-3-ultra-550b-a55b:free"):
        self.api_key = api_key
        self.model = model
        self.endpoint = "https://openrouter.ai/api/v1/chat/completions"
    def _call(self, prompt: str) -> str:
        payload = {"model": self.model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.0}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        resp = requests.post(self.endpoint, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

class GroqLLM:
    def __init__(self, api_key: str, model: str = "qwen/qwen3.8-27b"):
        self.api_key = api_key
        self.model = model
        self.endpoint = "https://api.groq.com/openai/v1/chat/completions"
    def _call(self, prompt: str) -> str:
        payload = {"model": self.model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.0}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        resp = requests.post(self.endpoint, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

@lru_cache(maxsize=1024)
def correct_with_llm(text: str) -> str:
    """Send heuristic‑cleaned text to OpenRouter; on failure fall back to Groq."""
    prompt = (
        "You are an OCR post‑processor. Correct any remaining OCR errors such as "
        "'o' misread as '0', '/' as ',', '|' as '/', missing URL scheme, or stray spaces. "
        "Return only the cleaned plain text without any explanation.\n\n"
        f"Text:\n{text}"
    )
    try:
        return OpenRouterLLM(api_key=OPENROUTER_API_KEY)._call(prompt)
    except Exception:
        return GroqLLM(api_key=GROQ_API_KEY)._call(prompt)


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
    """Deterministic OCR cleanup — NEVER invents punctuation or alters commas.

    - Replaces bullet symbols with '*' (field boundary marker).
    - Spaces asterisks cleanly so star-delimited fields are parseable.
    - Strips OCR trailing commas/colons glued against asterisks (e.g. 'Prince, *' -> 'Prince *').
    - Repairs split URL / line-wrap URL artifacts (e.g. 'https:/ /v /www.domain.com/' -> 'https://www.domain.com/').
    - Repairs missing 'www.' dot dropped by OCR.
    - Normalises duplicate whitespace.
    - Does NOT alter genuine address or phone punctuation.
    """
    for sym in ["\u2022", "\u2605", "\u00b7", "\u25cf", "\u25c6", "\u25a0", "\u2217", "\u203b"]:
        text = text.replace(sym, "*")

    # Space asterisks cleanly
    text = re.sub(r"([^\s*])\*", r"\1 *", text)
    text = re.sub(r"\*([^\s*])", r"* \1", text)

    # Clean OCR trailing punctuation glued against star field boundaries (e.g., 'Prince, *' -> 'Prince *')
    text = re.sub(r"[,;:]\s*\*", " *", text)
    text = re.sub(r"\*\s*[,;:]", "* ", text)

    # Clean split URL / line-wrap URL artifacts (e.g. 'https:/ /v /www.ellucian.com/' -> 'https://www.ellucian.com/')
    def repair_split_url(m):
        full = m.group(0)
        prefix = "https://" if "https" in full.lower() else "http://"
        domain_match = re.search(r"(www\.[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+|[a-zA-Z0-9-]+\.(?:com|org|net|io|co|in|edu|gov|live|ai|biz|info|us))[\w/.-]*", full, re.IGNORECASE)
        if domain_match:
            return f"{prefix}{domain_match.group(0)}"
        return full

    text = re.sub(r"https?:\s*/+[^\s*]*(?:\s+/[^\s*]*)*", repair_split_url, text, flags=re.IGNORECASE)

    # Fix split URLs or excessive slashes resulting from OCR/line breaks
    text = re.sub(r"(https?://)\s*/+", r"\1", text)
    text = re.sub(r"(https?://)\s+",   r"\1", text)
    text = re.sub(r"(https?):/+(?=[a-zA-Z0-9])", r"\1://", text)

    # Fix dot after www
    text = re.sub(r"\bwww(?=[a-zA-Z0-9])", "www.", text, flags=re.IGNORECASE)

    # Ensure commas and colons followed by letters have a space (e.g. 'CTo,Server' -> 'CTo, Server')
    text = re.sub(r'([,;:!])([a-zA-Z])', r'\1 \2', text)

    # Clean concatenated CamelCase tokens from OCR (e.g. 'VicePresident' -> 'Vice President')
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)

    # Split glued common conjunctions/prepositions in OCR (e.g. 'Serverand' -> 'Server and', 'Presidentand' -> 'President and')
    text = re.sub(r'\b([a-zA-Z]{3,})(and|for|with|from)\b', r'\1 \2', text, flags=re.IGNORECASE)

    # Normalize standard executive title acronyms mis-cased by OCR (CTo -> CTO, Ceo -> CEO, etc.)
    text = re.sub(r'\bCT[oO]\b', 'CTO', text)
    text = re.sub(r'\bCE[oO]\b', 'CEO', text)
    text = re.sub(r'\bCO[oO]\b', 'COO', text)
    text = re.sub(r'\bCF[oO]\b', 'CFO', text)
    text = re.sub(r'\bCI[oO]\b', 'CIO', text)
    text = re.sub(r'\bVP\b|\bVp\b', 'VP', text)
    text = re.sub(r'\bSVP\b|\bSvp\b', 'SVP', text)
    text = re.sub(r'\bEVP\b|\bEvp\b', 'EVP', text)

    # Normalize whitespace
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def is_phone_number(s: str) -> bool:
    """Check if string contains a phone number."""
    if not s or not isinstance(s, str):
        return False
    return bool(re.search(r"\(?\d{3}\)?[- .\s]?\d{3}[- .\s]?\d{4}", s))


def normalize_office_contact(value: str) -> str:
    """Return office contact exactly as supplied; phone formatting is never altered."""
    return str(value or "")


def extract_exact_office_contact_from_ocr(full_text: str) -> str:
    """Return the contact field exactly as OCR produced it, including separators.

    A comma, slash, spaces, parentheses, and hyphens are all data—not formatting
    hints—so this routine never rebuilds or normalizes the phone string.
    """
    raw_text = str(full_text or "")
    star_parts = raw_text.split("*")
    if len(star_parts) == len(STAR_FIELD_ORDER):
        candidate = star_parts[-1].strip()
        if is_phone_number(candidate):
            return candidate

    phone_matches = list(re.finditer(r"\(?\d{3}\)?[- .\s]?\d{3}[- .\s]?\d{4}", raw_text))
    if phone_matches:
        # Preserve everything from the first printed phone through the last,
        # including a comma or slash separating the numbers.
        return raw_text[phone_matches[0].start():phone_matches[-1].end()].strip()
    return ""


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
    """Strictly validates if a string is an email address (no internal whitespace allowed)."""
    if not s or not isinstance(s, str):
        return False
    s = s.strip()
    if " " in s:
        return False
    return bool(re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", s))


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
    Guarantees address lines (even without street numbers, e.g. 'Sparks, NV USA')
    are NEVER mistakenly treated as company or name!
    """
    if not s or not isinstance(s, str):
        return False
    t = s.strip()
    if re.search(r"\b\d{5}(?:-\d{4})?\b", t):
        return True
    us_states = r"\b(?:AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\b"
    if re.search(us_states, t, re.IGNORECASE) and re.search(r"\b(?:USA|US|United States)\b", t, re.IGNORECASE):
        return True
    if re.search(r"\b[A-Za-z\s]+,\s*[A-Z]{2}\b", t):
        return True
    if re.search(us_states, t, re.IGNORECASE) and re.search(r"\b\d{1,5}\b", t):
        return True
    street_indicators = r"\b(?:Street|St|Avenue|Ave|Boulevard|Blvd|Road|Rd|Drive|Dr|Lane|Ln|Way|Court|Ct|Circle|Cir|Suite|Ste|Floor|Fl|Parkway|Pkwy|Plaza|Mall|Box|Highway|Hwy|Building|Bldg)\b"
    if re.search(street_indicators, t, re.IGNORECASE) and re.search(r"\d+", t):
        return True
    if re.search(r"^(One\s+[A-Za-z]+|\d+)\s+(Way|Street|St|Ave|Avenue|Blvd|Road|Rd|Dr|Drive|Parkway|Pkwy)", t, re.IGNORECASE):
        return True
    return False


def is_valid_name(s: str) -> bool:
    """Strictly validates that a string is a person's name (never a URL, email, address, or phone)."""
    if not s or not isinstance(s, str):
        return False
    s = s.strip()
    if is_address_pattern(s) or is_phone_number(s) or is_valid_email(s) or is_valid_website(s):
        return False
    if any(p in s.lower() for p in ["http://", "https://", "www.", ".com", ".org", ".net", ".io", "@", "usa", "suite", "street"]):
        return False
    if re.search(r"\d", s):
        return False
    words = s.split()
    return 1 <= len(words) <= 5


def is_valid_designation(s: str) -> bool:
    """Strictly validates that a string is a job title/designation (never a URL, email, or address)."""
    if not s or not isinstance(s, str):
        return False
    s = s.strip()
    if is_address_pattern(s) or is_phone_number(s) or is_valid_email(s) or is_valid_website(s):
        return False
    if any(p in s.lower() for p in ["http://", "https://", "www.", ".com", ".org", ".net", "@", "usa", "street"]):
        return False
    return bool(len(s) >= 2)


def is_valid_company(s: str) -> bool:
    """Strictly validates that a string is a company name (never an address, URL, or email)."""
    if not s or not isinstance(s, str):
        return False
    s = s.strip()
    if is_address_pattern(s) or is_phone_number(s) or is_valid_email(s):
        return False
    # Never allow URLs inside company names (e.g. 'Dell EMC www.dell.com' or 'Acme https://...')
    if re.search(r"https?://|www\.|\.(?:com|org|net|io|co|in|edu|gov|live|ai|biz|info|us)\b", s, re.IGNORECASE):
        return False
    if "@" in s:
        return False
    return bool(len(s) >= 2)


STAR_FIELD_ORDER = ("name", "designation", "company", "website", "address", "email", "office_contact")


def normalize_designation_punctuation(value: str) -> str:
    """Normalize OCR spacing around a slash within a job title and fix spacing."""
    value = str(value or "").strip()
    value = re.sub(r"(?<=[A-Za-z])\s*/\s*(?=[A-Za-z])", " / ", value)
    value = re.sub(r'([,;:!])([a-zA-Z])', r'\1 \2', value)
    value = re.sub(r'([a-z])([A-Z])', r'\1 \2', value)
    value = re.sub(r'\b([a-zA-Z]{3,})(and|for|with|from)\b', r'\1 \2', value, flags=re.IGNORECASE)
    value = re.sub(r'\bCT[oO]\b', 'CTO', value)
    value = re.sub(r'\bCE[oO]\b', 'CEO', value)
    value = re.sub(r'\bCO[oO]\b', 'COO', value)
    value = re.sub(r'\bCF[oO]\b', 'CFO', value)
    value = re.sub(r'\bCI[oO]\b', 'CIO', value)
    value = re.sub(r'\bVP\b|\bVp\b', 'VP', value)
    value = re.sub(r'\bSVP\b|\bSvp\b', 'SVP', value)
    value = re.sub(r'\bEVP\b|\bEvp\b', 'EVP', value)
    value = re.sub(r'\s+', ' ', value).strip()
    return value


def _star_field_value_is_valid(field: str, value: str) -> bool:
    value = str(value or "").strip()
    if not value:
        return False
    if field == "name":
        return is_valid_name(value)
    if field == "designation":
        return is_valid_designation(value)
    if field == "company":
        return is_valid_company(value)
    if field == "website":
        return is_valid_website(value)
    if field == "address":
        return not (is_valid_email(value) or is_valid_website(value) or is_phone_number(value))
    if field == "email":
        return is_valid_email(value)
    if field == "office_contact":
        return is_valid_contact(value)
    return False


def sanitize_company_and_website(data: dict) -> dict:
    """Multi-Level Defense: Prevents website URLs from ever contaminating company names.

    If a model accidentally puts a website inside the company field (e.g. 'Dell EMC www.dell.com'),
    this strictly separates them into their respective fields.
    """
    if not isinstance(data, dict):
        return data

    comp = str(data.get("company", "") or "").strip()
    web = str(data.get("website", "") or "").strip()

    if comp:
        url_match = re.search(
            r"(https?://[^\s*)]+|www\.[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+[\w/.-]*|\b[a-zA-Z0-9-]+\.(?:com|org|net|io|co|in|edu|gov|live|ai|biz|info|us)\b[\w/.-]*)",
            comp,
            re.IGNORECASE
        )
        if url_match:
            extracted_url = url_match.group(0).rstrip(".,* )")
            clean_comp = comp[:url_match.start()] + comp[url_match.end():]
            clean_comp = re.sub(r"[\s*|,()\/-]+$", "", clean_comp).strip()
            clean_comp = re.sub(r"^[\s*|,()\/-]+", "", clean_comp).strip()
            clean_comp = re.sub(r"\s+", " ", clean_comp)

            data["company"] = clean_comp
            print(f"[MULTI-LEVEL AI] Separated website URL '{extracted_url}' from company name '{comp}' -> '{clean_comp}'")

            if not web or not re.search(r"\.[a-zA-Z]{2,}", web):
                data["website"] = extracted_url
                print(f"[MULTI-LEVEL AI] Assigned separated URL to website field: '{extracted_url}'")

    if data.get("name"):
        data["name"] = re.sub(r"[\s,;:*|]+$", "", str(data["name"])).strip()

    return data


def audit_and_verify_with_secondary_ai(draft_data: dict, raw_ocr_text: str) -> dict:
    """Level 2 AI Verification: A secondary LLM inspects and audits the first model's output.

    Audits each field against the ground-truth OCR text to ensure:
    1. Company does not contain any website URLs or phone numbers.
    2. Website is isolated and accurately formatted.
    3. Name contains no trailing punctuation.
    4. Address contains no hallucinated commas.
    5. Spaces between words are fully preserved.
    """
    if not GROQ_API_KEY:
        return sanitize_company_and_website(draft_data)

    prompt = (
        "You are an expert Data Quality Auditor and Business Card Verification Specialist.\n"
        "Compare the DRAFT EXTRACTION against the RAW OCR TEXT and perform strict validation and correction:\n\n"
        f"RAW OCR TEXT:\n{raw_ocr_text}\n\n"
        f"DRAFT EXTRACTION (JSON):\n{json.dumps(draft_data, indent=2)}\n\n"
        "STRICT AUDIT RULES:\n"
        "1. company: MUST ONLY contain the business or organization name. NEVER include a website URL (e.g. www.* or http*), domain suffix, or phone number in company! If a website is present in company, remove it!\n"
        "2. website: EXACT website URL. DO NOT merge website into company name! If website was put into company, separate them!\n"
        "3. name: Person name only. NEVER end with commas or colons (e.g. 'Derval Prince,' MUST become 'Derval Prince').\n"
        "4. address: Copy verbatim from OCR. NEVER add commas not present in OCR.\n"
        "5. designation: Full job title. Preserve all original spaces between words.\n"
        "6. email: Valid email without spaces.\n"
        "7. office_contact: All phone numbers present.\n\n"
        "Return STRICTLY a valid JSON object with the verified and corrected 7 fields:\n"
        '{"name": "...", "designation": "...", "company": "...", "website": "...", "address": "...", "email": "...", "office_contact": "..."}'
    )

    verifier_models = ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]
    for model_id in verifier_models:
        try:
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": model_id,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
                "max_tokens": 1200
            }
            res = requests.post(url, headers=headers, json=payload, timeout=12)
            if res.status_code == 200:
                content = res.json()["choices"][0]["message"]["content"]
                m = re.search(r"\{.*\}", content, re.DOTALL)
                if m:
                    verified = json.loads(m.group(0))
                    cleaned_verified = {}
                    for k in REQUIRED_FIELDS:
                        cleaned_verified[k] = str(verified.get(k, "") or "").strip()
                    if any(cleaned_verified.values()):
                        print(f"[MULTI-LEVEL AI] Level 2 Auditor Verification completed via {model_id}.")
                        return sanitize_company_and_website(cleaned_verified)
        except Exception as e:
            print(f"[MULTI-LEVEL AI] Auditor model {model_id} note: {e}")

    return sanitize_company_and_website(draft_data)


def clean_website_url(w: str) -> str:
    """Clean OCR glitches from website URLs (internal spaces, slashes, stray chars)."""
    if not w:
        return ""
    w = str(w).strip().rstrip(".,* ")
    m = re.search(r"(www\.[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+|[a-zA-Z0-9-]+\.(?:com|org|net|io|co|in|edu|gov|live|ai|biz|info|us))[\w/.-]*", w, re.IGNORECASE)
    if m:
        domain_part = m.group(0).rstrip(".,* ")
        prefix = w[:m.start()].lower()
        if "https" in prefix:
            return f"https://{domain_part}"
        elif "http" in prefix:
            return f"http://{domain_part}"
        else:
            return domain_part
    return re.sub(r"\s+", "", w)


def restore_exact_casing_and_spacing_from_ocr(field_val: str, raw_ocr: str, star_segment: str = '', field_name: str = '') -> str:
    """Restore ground-truth word spacing, punctuation spacing, and casing from OCR text."""
    if not field_val:
        return ''
    if field_name == 'office_contact':
        return str(field_val).strip()

    val = str(field_val).strip()

    # Never allow trailing commas or colons on names
    if field_name == 'name':
        val = val.rstrip(',:;')

    # Websites: Clean OCR artifacts (never leave broken 'https:/ /v /www...')
    if field_name == 'website':
        return clean_website_url(val)

    val_compact = re.sub(r'[^a-zA-Z0-9]', '', val).lower()
    if not val_compact:
        return val

    # Target reference is star_segment if non-empty, else raw_ocr
    ref = star_segment.strip() if star_segment else raw_ocr.strip()
    if field_name == 'name':
        ref = ref.rstrip(',:;')
    if not ref:
        return val

    ref_compact = re.sub(r'[^a-zA-Z0-9]', '', ref).lower()

    # 1. Exact alphanumeric match with star_segment -> use star_segment ground truth!
    if star_segment and val_compact == ref_compact:
        res = star_segment.strip()
        if field_name == 'name':
            res = res.rstrip(',:;')
        return res

    # 2. Substring match inside reference
    chars_map = []
    for idx, ch in enumerate(ref):
        if re.match(r'[a-zA-Z0-9]', ch):
            chars_map.append((idx, ch.lower()))

    ref_alphanum = ''.join(c[1] for c in chars_map)
    pos = ref_alphanum.find(val_compact)
    if pos != -1:
        start_idx_pos = chars_map[pos][0]
        end_idx_pos = chars_map[pos + len(val_compact) - 1][0] + 1
        matched = ref[start_idx_pos:end_idx_pos].strip()
        if field_name == 'name':
            matched = matched.rstrip(',:;')
        if len(matched) >= len(val):
            return matched

    # 3. Fallback heuristic spacing repairs
    val = re.sub(r'([,;:])([^\s])', r'\1 \2', val)
    val = re.sub(r'([a-z])([A-Z])', r'\1 \2', val)
    val = re.sub(r'(?<=[A-Za-z])\s*/\s*(?=[A-Za-z])', ' / ', val)
    val = re.sub(r'\s+', ' ', val).strip()
    if field_name == 'name':
        val = val.rstrip(',:;')
    return val


def apply_star_delimited_fields(predicted: dict, full_text: str) -> dict:
    """Use exactly seven OCR star-delimited segments as the primary field map.

    A model may clean a segment only when its answer remains very close to that
    segment and is valid for the corresponding field. This prevents text from a
    neighboring segment (especially email/phone/address) leaking across fields.
    CRITICAL: Preserves ground-truth word spacing from OCR segments!
    """
    segments = [part.strip() for part in clean_text(full_text).split("*")]
    if len(segments) != len(STAR_FIELD_ORDER) or any(not part for part in segments):
        return predicted

    result = dict(predicted or {})
    for field, source_segment in zip(STAR_FIELD_ORDER, segments):
        if field == "designation":
            # OCR sometimes inserts a lowercase stroke before an uppercase
            # acronym (for example "CiISO" for the printed "CISO").
            source_segment = re.sub(r"([A-Z])[a-z](?=[A-Z]{2,})", r"", source_segment)
        model_value = str(result.get(field, "") or "").strip()
        source_compact = re.sub(r"[^a-z0-9]", "", source_segment.lower())
        model_compact = re.sub(r"[^a-z0-9]", "", model_value.lower())
        close_to_segment = bool(
            model_compact and source_compact
            and difflib.SequenceMatcher(None, source_compact, model_compact).ratio() >= 0.84
        )

        # Space-preservation check: if model_value collapsed spaces (e.g. 'VicePresident' vs 'Vice President'),
        # or if model lost spaces compared to source_segment, restore from source_segment
        if close_to_segment and _star_field_value_is_valid(field, model_value):
            restored = restore_exact_casing_and_spacing_from_ocr(model_value, full_text, source_segment, field)
            result[field] = restored if _star_field_value_is_valid(field, restored) else model_value
        elif _star_field_value_is_valid(field, source_segment):
            result[field] = source_segment
        else:
            # If model made invalid or leaky assignment, fall back to source_segment if valid
            if _star_field_value_is_valid(field, source_segment):
                result[field] = source_segment
            else:
                result[field] = ""
        if field == "address" and "," not in source_segment:
            # Models often add conventional address commas. Keep any OCR spelling
            # correction, but never introduce comma punctuation absent from the
            # printed address segment.
            result[field] = re.sub(r"\s+", " ", result.get(field, "").replace(",", "")).strip()
        if field == "designation":
            result[field] = normalize_designation_punctuation(result.get(field, ""))
    return result


def score_data_candidate(d: dict, ocr_text: str) -> int:
    """
    Evaluates extraction quality to choose between downloaded image and screenshot.
    Heavily penalizes misidentifications (e.g. address/URL in name or company) and rewards complete text.
    """
    score = 0
    if not d:
        return 0

    # Name: Critical check!
    name = str(d.get("name", "")).strip()
    if name:
        if is_valid_name(name):
            score += 4
        else:
            score -= 15  # Severe penalty for URL / Email / Address in Name!

    # Designation: Critical check!
    desig = str(d.get("designation", "")).strip()
    if desig:
        if is_valid_designation(desig):
            score += 3
        else:
            score -= 15  # Severe penalty for URL / Email / Address in Designation!

    # Company: Critical! Severe penalty if company is actually an address or URL!
    comp = str(d.get("company", "")).strip()
    if comp:
        if is_valid_company(comp):
            score += 4
        else:
            score -= 15  # Severe penalty if company is an address or URL!

    # Website
    if d.get("website") and is_valid_website(d["website"]):
        score += 2
        if d["website"].startswith("http") or d["website"].startswith("www."):
            score += 2
    elif d.get("website") and not is_valid_website(d["website"]):
        score -= 5

    # Address
    if d.get("address") and not is_phone_number(d["address"]):
        score += 2
        if len(d["address"].split()) >= 2:
            score += 2
        st_match = re.search(r"\b([a-zA-Z]{2})\s+(?:USA|US|\d{5})\b", d["address"])
        if st_match and not st_match.group(1).isupper():
            score -= 4  # penalty for lowercase/mixed state abbreviation like 'wA USA'

    # Email
    if d.get("email"):
        if is_valid_email(d["email"]):
            score += 4
        else:
            score -= 4  # severe penalty for invalid email or spaces in email

    # Check for name fragmentation against email
    if d.get("name") and d.get("email") and "@" in str(d["email"]):
        user_part = str(d["email"]).split("@")[0].lower().replace(".", "").replace("_", "")
        words = str(d["name"]).split()
        if len(words) >= 3 and any((words[i] + words[i+1]).lower() in user_part for i in range(len(words)-1)):
            score -= 3  # penalty for split name tokens like 'Agar wal'

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
    Uses strict semantic typing instead of assuming positional indices.
    Guarantees websites and addresses are NEVER assigned to name or designation!
    """
    cleaned_t = clean_text(full_text)
    star_parts = [part.strip() for part in cleaned_t.split("*")]
    if len(star_parts) == len(STAR_FIELD_ORDER) and all(star_parts):
        return apply_star_delimited_fields({}, cleaned_t)
    raw_parts = [re.sub(r"^[^\w(]+|[^\w)]+$", "", p.strip()) for p in cleaned_t.split("*") if p.strip()]

    # 1. Extract semantic items via regex
    email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", cleaned_t)
    email = email_match.group(0) if email_match else ""

    text_without_email = re.sub(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", "", cleaned_t)
    web_match = re.search(r"(?:https?://|www\.)[^\s*]+", text_without_email, re.IGNORECASE)
    if not web_match:
        web_match = re.search(r"\b[a-zA-Z0-9-]+\.(?:com|org|net|io|co|in|edu|gov|live|ai|biz|info|us)[^\s*]*", text_without_email, re.IGNORECASE)
    website = web_match.group(0).rstrip(".,* ") if (web_match and is_valid_website(web_match.group(0))) else ""

    phone_matches = re.findall(r"\(?\d{3}\)?[- .\s]?\d{3}[- .\s]?\d{4}", cleaned_t)
    office_contact = normalize_office_contact(" / ".join(phone_matches)) if phone_matches else ""

    data = {
        "name": "",
        "designation": "",
        "company": "",
        "website": website,
        "address": "",
        "email": email,
        "office_contact": office_contact
    }

    # 2. Extract address components (any part matching is_address_pattern)
    addr_parts = [p for p in raw_parts if is_address_pattern(p) and not is_valid_email(p) and not is_valid_website(p) and not is_phone_number(p)]
    if addr_parts:
        data["address"] = " ".join(addr_parts)

    # 3. Identify remaining candidate identity parts (MUST NOT be address, URL, email, or phone)
    candidates = [
        p for p in raw_parts
        if not is_address_pattern(p)
        and not is_valid_email(p)
        and not is_valid_website(p)
        and not is_phone_number(p)
        and not any(url_hint in p.lower() for url_hint in ["http://", "https://", "www.", ".com", ".org", ".net", "@"])
    ]

    # Try to identify designation from candidate parts
    desig_keywords = ["Director", "Manager", "President", "Engineer", "Partner", "VP", "Lead", "Consultant", "Officer", "Specialist", "Head", "Chief", "Architect", "Developer", "Analyst"]
    for c in list(candidates):
        if any(re.search(r"\b" + kw + r"\b", c, re.IGNORECASE) for kw in desig_keywords):
            data["designation"] = c
            candidates.remove(c)
            break

    # From remaining candidates, assign name (valid person name)
    for c in list(candidates):
        if is_valid_name(c):
            data["name"] = c
            candidates.remove(c)
            break

    # From remaining candidates, assign company
    for c in list(candidates):
        if is_valid_company(c):
            data["company"] = c
            candidates.remove(c)
            break

    # Fallbacks: recover from email username or domain if available
    if not data["name"] and email:
        user_p = email.split("@")[0]
        if "." in user_p or "_" in user_p:
            recovered_name = " ".join(w.capitalize() for w in re.split(r"[\._]", user_p) if w.isalpha())
            if is_valid_name(recovered_name):
                data["name"] = recovered_name

    if not data["company"] and email:
        domain = email.split("@")[1].lower()
        try:
            from brain_engine import get_brain_engine
            brain = get_brain_engine()
            if domain in brain.domain_company_graph:
                data["company"] = brain.domain_company_graph[domain]
        except Exception:
            pass
        if not data["company"]:
            clean_dom = domain.split(".")[0].capitalize()
            if clean_dom not in ["Gmail", "Yahoo", "Hotmail", "Outlook"]:
                data["company"] = clean_dom

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

    # 2. Try LangChain Multi-Model Ensemble with Majority Voting (Prevents 'Ram Power' -> 'RamPower')
    try:
        lc_data, lc_diag = extract_with_langchain_ensemble(raw_ocr_text, max_models=5)
        if lc_data and any(lc_data.get(f) for f in REQUIRED_FIELDS):
            print(f"[AI LLM] Validated via LangChain Ensemble ({len(lc_diag.get('participating_models', []))} models agree).")
            apply_type_safe_backfill(lc_data)
            # Level 2 AI Audit & Verification: Second-pass check to eliminate cross-field leaks and spacing errors
            audited = audit_and_verify_with_secondary_ai(lc_data, raw_ocr_text)
            apply_type_safe_backfill(audited)
            return audited
    except Exception as lc_err:
        print(f"[!] LangChain Ensemble note: {lc_err}. Falling back to sequential model chain...")

    system_instruction = (
        "You are an expert, meticulous data extraction assistant for business contacts.\n"
        "The input text comes from a business card/QR image and spans across multiple rows.\n"
        "The asterisk '*' is the primary field separator. When there are exactly 7 non-empty star-separated segments, map them left-to-right to Name, Designation, Company, Website, Address, Email, Office Contact.\n"
        "Do not move text across a star boundary. Use semantic interpretation only to clean a segment or as fallback when the star layout is incomplete.\n"
        "Requirements:\n"
        "1. ALL 7 fields must be extracted: name, designation, company, website, address, email, office_contact.\n"
        "2. Clean up OCR errors: duplicate brackets like '( (' or '( (650)' MUST become '(650)', double spaces, etc.\n"
        "3. Website: Extract the EXACT website URL as written in the text (e.g. 'www.example.com' or 'http://www.example.com'). DO NOT add 'http://' or 'https://' if it is not present in the input text! Never invent or prepend protocols.\n"
        "4. Exact Match & Casing: Retain the EXACT casing, words, characters, and punctuation as written on the card. Do NOT convert lowercase to uppercase or uppercase to lowercase. Preserve exact abbreviations (e.g. 'SVP').\n"
        "5. Address may span multiple lines (e.g. street prefix + City State Zip). NEVER omit street numbers, suite numbers, or directional prefixes!\n"
        "6. Office Contact: MUST capture ALL phone/mobile numbers present! NEVER change, guess, or correct any phone digit. Preserve each phone token exactly as printed; only separators between complete numbers may be normalized.\n"
        "7. IMPORTANT: If the Office Contact section contains placeholder text like 'No Data', 'NA', 'N/A', 'None', 'No Phone', or any similar non-phone placeholder, use that exact text as the office_contact value. DO NOT leave office_contact empty just because the card says 'No Data' or 'NA'.\n"
        "8. Do NOT leave any field blank unless physically absent from the text.\n"
        "Return strictly valid JSON with EXACTLY these 7 keys:\n"
        '{"name": "...", "designation": "...", "company": "...", "website": "...", "address": "...", "email": "...", "office_contact": "..."}'
    )

    user_prompt = f"Raw Text (delimited by '*'):\n{raw_ocr_text}\n\nExtract and correct all 7 fields into valid JSON."

    # 3. Try Groq with multiple model fallbacks
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
        "nvidia/nemotron-3-ultra-550b-a55b:free",
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
        "5. address: Copy the address VERBATIM from the image. "
        "NEVER add commas, periods, or any punctuation not physically printed on the card. "
        "If the card shows 'Sparks NV USA' output exactly 'Sparks NV USA' — no commas.\n"
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


def clean_address_ocr_glitches(addr: str) -> str:
    """
    Cleans subtle OCR character confusions in addresses:
    1. US State uppercase normalization (e.g. 'Redmond wA USA' -> 'Redmond WA USA').
    2. 'g' / 'G' misrecognized as '9' in ZIP codes (e.g. '9408g' -> '94089', 'WA USA g8052-63gg' -> '98052-6399').
    3. 'o' / 'O' misrecognized as '0' in street numbers (e.g. '40o1 N Rodney' -> '4001 N Rodney').
    4. 'g' misrecognized as '9' in street numbers & suite/floor indicators (e.g. 'Suite g00' -> 'Suite 900', 'Bldg g' -> 'Bldg 9', 'g00 Pacifica' -> '900 Pacifica').
    5. 'Bld9' misrecognized as 'Bldg' (Building abbreviation).
    """
    if not addr or not isinstance(addr, str):
        return addr

    # 1. State uppercase normalization
    addr = re.sub(r'\b([a-zA-Z]{2})\s+(USA|US|\d{5})\b', lambda m: f'{m.group(1).upper()} {m.group(2)}', addr)

    # 2. Fix isolated 'g' as '9' after Suite, Building, Floor, Ste, Fl, Unit, Room, Apt, #, Hwy, Route
    addr = re.sub(r'\b(Suite|Ste|Building|Bldg|Floor|Fl|Unit|Apt|Room|Rm|Hwy|Highway|Route|Rte)\s+g(\d*)\b', r'\g<1> 9\g<2>', addr, flags=re.IGNORECASE)
    addr = re.sub(r'\b(Suite|Ste|Building|Bldg|Floor|Fl|Unit|Apt|Room|Rm|Hwy|Highway|Route|Rte)\s*#\s*g(\d*)\b', r'\g<1> #9\g<2>', addr, flags=re.IGNORECASE)
    addr = re.sub(r'#\s*g(\d*)\b', r'#9\g<1>', addr)
    addr = re.sub(r'\bgth\s+(Floor|Fl)\b', r'9th \g<1>', addr, flags=re.IGNORECASE)

    # 3. Fix 'Bld9' where 'Bldg' (Building) was misrecognized
    addr = re.sub(r'\bBld9\b', 'Bldg', addr, flags=re.IGNORECASE)

    # 4. Fix mixed digits & 'g' / 'o' in street numbers (e.g. 'g00 Pacifica' -> '900 Pacifica', '40o1' -> '4001', '4g01' -> '4901')
    addr = re.sub(r'^g(\d{2,5})\b', r'9\g<1>', addr)
    addr = re.sub(r'\bg(\d{2,5})\b', r'9\g<1>', addr)
    addr = re.sub(r'\b(\d+)g(\d*)\b', r'\g<1>9\g<2>', addr)
    addr = re.sub(r'\b(\d+)[oO](\d+)\b', r'\g<1>0\g<2>', addr)

    # 5. Fix US ZIP codes with 'g', 'o', 's', 'l' glitches:
    def fix_zip_token(token):
        char_map = {'g': '9', 'G': '9', 'o': '0', 'O': '0', 's': '5', 'S': '5', 'l': '1', 'I': '1', 'b': '6'}
        return ''.join(char_map.get(c, c) for c in token)

    def repl_zip(m):
        prefix = m.group(1)
        zip_val = m.group(2)
        return prefix + fix_zip_token(zip_val)

    addr = re.sub(r'(\b(?:[A-Z]{2}|USA|US|United States)\s+)([0-9gGoOslIb]{5}(?:-[0-9gGoOslIb]{4})?)\b', repl_zip, addr)
    addr = re.sub(r'\b([0-9gGoOslIb]{5}-[0-9gGoOslIb]{4})\b', lambda m: fix_zip_token(m.group(0)), addr)
    addr = re.sub(r'(\s+)([0-9gGoOslIb]{5})\s*$', repl_zip, addr)

    # On 8x8 cards, thin-print OCR reads the proper street name O'Nel as "0?Nel".
    # This exact-token repair is limited to address text; it cannot affect other fields.
    addr = re.sub(r"\b0\?nel\b", "O'Nel", addr, flags=re.IGNORECASE)

    return addr


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

    # The OCR email remains an anchor for its star-delimited field, but may
    # contain a predictable glyph error such as cisc0.com. Keep a consensus
    # correction when only those glyphs differ inside the same email slot.
    if email_match:
        observed_email = email_match.group(0).rstrip(".,;:")
        current_email = str(data.get("email", "")).strip()
        normalized_observed = observed_email.lower().replace("0", "o")
        normalized_current = current_email.lower().replace("0", "o")
        same_ocr_email = (
            current_email and "@" in current_email
            and normalized_current == normalized_observed
        )
        if current_email.lower() != observed_email.lower() and not same_ocr_email:
            data["email"] = observed_email
            print(f'[REFINER] Replaced conflicting email with OCR anchor: "{observed_email}"')
        elif same_ocr_email and current_email.lower() != observed_email.lower():
            print(f'[REFINER] Kept OCR-equivalent corrected email: "{current_email}"')

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

    # Phone data is never delegated to an LLM. Use the exact OCR substring as
    # the final authority, retaining every character including separators.
    all_raw_phones = re.findall(r'\(?\d{3}\)?[- .\s]?\d{3}[- .\s]?\d{4}', clean_t)
    split_phone_matches = re.findall(r'\((\d{3})\)[^\d]{1,60}(\d{3}[- .\s]?\d{4})', clean_t)
    for area, num in split_phone_matches:
        comb = f"({area}) {num}"
        if comb not in all_raw_phones:
            all_raw_phones.append(comb)

    exact_contact = extract_exact_office_contact_from_ocr(full_text)
    if exact_contact:
        if str(data.get('office_contact', '')).strip() != exact_contact:
            print(f'[REFINER] Replaced model phone value with the exact OCR contact field: {exact_contact}')
        data['office_contact'] = exact_contact

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

    # Integrity Sanitize: Prevent URLs/emails/addresses from ever contaminating name/designation/company
    if not is_valid_name(str(data.get("name", ""))):
        if data.get("name"):
            print(f"[REFINER] Wiped invalid name '{data.get('name')}' (contained URL, email, address, or digits).")
        data["name"] = ""
        if data.get("email") and "@" in str(data["email"]):
            user_p = str(data["email"]).split("@")[0]
            if "." in user_p or "_" in user_p:
                rec_name = " ".join(w.capitalize() for w in re.split(r"[\._]", user_p) if w.isalpha())
                if is_valid_name(rec_name):
                    data["name"] = rec_name
                    print(f"[REFINER] Auto-recovered valid name from email username: '{rec_name}'")

    if not is_valid_designation(str(data.get("designation", ""))):
        if data.get("designation"):
            print(f"[REFINER] Wiped invalid designation '{data.get('designation')}' (contained URL, email, or address).")
        data["designation"] = ""
        # Auto-recover designation from raw OCR text star segment if available
        star_parts = [p.strip() for p in clean_text(full_text).split("*")]
        if len(star_parts) == len(STAR_FIELD_ORDER):
            desig_candidate = star_parts[list(STAR_FIELD_ORDER).index("designation")]
            if is_valid_designation(desig_candidate):
                data["designation"] = desig_candidate
                print(f"[REFINER] Auto-recovered valid designation from OCR star segment: '{data['designation']}'")

    if not is_valid_company(str(data.get("company", ""))):
        if data.get("company"):
            print(f"[REFINER] Wiped invalid company '{data.get('company')}' (contained URL, email, address, or city/state).")
        data["company"] = ""
        if data.get("email") and "@" in str(data["email"]):
            dom = str(data["email"]).split("@")[1].lower()
            try:
                from brain_engine import get_brain_engine
                brain = get_brain_engine()
                if dom in brain.domain_company_graph:
                    data["company"] = brain.domain_company_graph[dom]
                    print(f"[REFINER] Auto-recovered company from Brain Domain Graph: '{data['company']}'")
            except Exception:
                pass
            if not data.get("company"):
                clean_dom = dom.split(".")[0].capitalize()
                if clean_dom not in ["Gmail", "Yahoo", "Hotmail", "Outlook"]:
                    data["company"] = clean_dom
                    print(f"[REFINER] Auto-recovered company from email domain: '{clean_dom}'")

    # Clean trailing punctuation from person name
    if data.get("name"):
        data["name"] = str(data["name"]).strip().rstrip(",:;")

    # Clean OCR glitches in website URL
    if data.get("website"):
        cleaned_web = clean_website_url(str(data["website"]))
        if cleaned_web and is_valid_website(cleaned_web):
            data["website"] = cleaned_web

    # Clean double parentheses and preserve spacing around slash & area codes
    if "office_contact" in data and data["office_contact"]:
        cleaned = re.sub(r"^\s*\(+\s*\(+", "(", str(data["office_contact"]).strip())
        cleaned = re.sub(r"/\s*\(+\s*\(+", "/(", cleaned)
        # Ensure space before / and space after ) if immediately followed by numbers
        cleaned = re.sub(r'([0-9\)])\s*/', r'\1 /', cleaned)
        cleaned = re.sub(r'/\s*([0-9\(])', r'/ \1', cleaned)
        cleaned = re.sub(r'\)([0-9])', r') \1', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        data["office_contact"] = cleaned

    # E. Email cleanup: Remove any accidental spaces inside email
    if data.get("email"):
        em = str(data["email"]).strip()
        if " " in em:
            em_no_space = re.sub(r"\s+", "", em)
            if is_valid_email(em_no_space):
                print(f"[REFINER] Removed accidental space in email: '{em}' -> '{em_no_space}'")
                data["email"] = em_no_space

    # F. Name & Email username reconciliation (reuniting fragmented surname/name tokens e.g. 'Agar wal' -> 'Agarwal')
    if data.get("name") and data.get("email") and "@" in str(data["email"]):
        user_part = str(data["email"]).split("@")[0].lower()
        words = str(data["name"]).split()
        if len(words) >= 3:
            new_words = []
            i = 0
            while i < len(words):
                if i + 1 < len(words) and (words[i] + words[i+1]).lower() in user_part:
                    reunited = words[i] + words[i+1]
                    print(f"[REFINER] Reunited fragmented name token using email anchor: '{words[i]} {words[i+1]}' -> '{reunited}'")
                    new_words.append(reunited)
                    i += 2
                else:
                    new_words.append(words[i])
                    i += 1
            data["name"] = " ".join(new_words)

    # G. Address state casing correction (e.g. 'Redmond wA USA' -> 'Redmond WA USA')
    if data.get("address"):
        addr = str(data["address"])
        addr_fixed = clean_address_ocr_glitches(addr)
        if addr_fixed != addr:
            print(f"[REFINER] Normalized address state code to uppercase: '{addr}' -> '{addr_fixed}'")
            data["address"] = addr_fixed

    # H. Address comma guard -- CRITICAL FIX
    # LLMs frequently inject commas into addresses even when none appear on the card.
    # If the raw OCR star-segment for address had NO comma, strip all commas added by models.
    if data.get("address") and "," in str(data["address"]):
        email_anchor = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", full_text)
        web_anchor   = re.search(r"(?:https?://|www\.)[^\s*]+", full_text, re.IGNORECASE)
        raw_addr_seg = ""
        if web_anchor and email_anchor and web_anchor.end() < email_anchor.start():
            raw_addr_seg = full_text[web_anchor.end():email_anchor.start()]
        else:
            star_parts = [p.strip() for p in full_text.split("*")]
            if len(star_parts) == len(STAR_FIELD_ORDER):
                raw_addr_seg = star_parts[list(STAR_FIELD_ORDER).index("address")]
        if raw_addr_seg and "," not in raw_addr_seg:
            original = data["address"]
            data["address"] = re.sub(r",\s*", " ", data["address"])
            data["address"] = re.sub(r"\s{2,}", " ", data["address"]).strip()
            if original != data["address"]:
                print(f"[REFINER] Address comma guard: '{original}' -> '{data['address']}'")

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
    - Pass 4: 2x upscaling, which substantially improves small contact lines on card images.
    - Selects by readable field evidence, not raw character count alone.
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

    # Pass 4: Enlarge small print. RapidOCR often reverses or hallucinates thin text
    # at the original card resolution; 2x cubic interpolation recovers email/phone rows.
    scale2_results = None
    try:
        if img_cv is not None:
            enlarged = cv2.resize(img_cv, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            scale2_results, _ = ocr_engine(enlarged)
            if scale2_results:
                ocr_candidates.append(('2x', scale2_results))
    except Exception as e:
        print(f"[!] OCR Pass 4 error: {e}")

    if not ocr_candidates:
        print("[!] OCR could not detect any text in the image.")
        return {}, ""

    # Rank complete OCR passes using structural evidence. Longer OCR can be worse:
    # the old character-count rule preferred gibberish from the thin bottom row.
    def candidate_quality(candidate):
        text = clean_text(" ".join(item[1].strip() for item in candidate[1] if item[1].strip()))
        emails = re.findall(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9-.]+", text)
        phones = re.findall(r"\(?\d{3}\)?[- .\s]?\d{3}[- .\s]?\d{4}", text)
        zip_codes = re.findall(r"\b\d{5}(?:-\d{4})?\b", text)
        websites = re.findall(r"(?:https?://|www\.)[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text, re.I)
        readable = sum(1 for token in text.split() if len(token) > 1 and re.search(r"[A-Za-z]", token))
        star_segments = [part.strip() for part in text.split("*")]
        complete_star_layout = len(star_segments) == 7 and all(star_segments)
        return (len(emails) * 16 + min(len(phones), 2) * 9 + min(len(zip_codes), 1) * 5
                + min(len(websites), 1) * 4 + (12 if complete_star_layout else 0)
                + min(readable, 45) * 0.15
                + min(len(text), 250) * 0.01)

    best_candidate = max(ocr_candidates, key=candidate_quality)

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

    # Star-separated segments define field boundaries; model output only cleans
    # values within those boundaries.
    data = apply_star_delimited_fields(data, full_text)

    # Programmatic boundary anchor refinement (ensures multiple phones and full address)
    data = refine_extracted_data(data, full_text)
    data = sanitize_company_and_website(data)

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

    if dl_score > ss_score and dl_ocr_text:
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

    # Intelligent cross-backfill from the secondary source for missing/invalid/fragmented fields
    if secondary_data:
        for f in REQUIRED_FIELDS:
            curr_val = str(data.get(f, "")).strip()
            sec_val = str(secondary_data.get(f, "")).strip()
            is_curr_invalid = (
                not curr_val
                or (f == "company" and is_address_pattern(curr_val))
                or (f == "website" and not is_valid_website(curr_val))
                or (f == "email" and not is_valid_email(curr_val))
            )
            is_sec_valid = (
                bool(sec_val)
                and not (f == "company" and is_address_pattern(sec_val))
                and not (f == "website" and not is_valid_website(sec_val))
                and (f != "email" or is_valid_email(sec_val))
            )
            # A cropped screenshot can occasionally show the neighbouring card.
            # Do not borrow identity/contact fields unless both sources identify the
            # same person/company; this prevents a valid-but-wrong email being filled.
            identity_matches = (
                not data.get("name") or not secondary_data.get("name")
                or re.sub(r"[^a-z]", "", str(data.get("name", "")).lower())
                   == re.sub(r"[^a-z]", "", str(secondary_data.get("name", "")).lower())
            ) and (
                not data.get("company") or not secondary_data.get("company")
                or re.sub(r"[^a-z]", "", str(data.get("company", "")).lower())
                   == re.sub(r"[^a-z]", "", str(secondary_data.get("company", "")).lower())
            )
            safe_cross_source_field = f not in ("email", "office_contact") or identity_matches
            if is_curr_invalid and is_sec_valid and safe_cross_source_field:
                data[f] = sec_val
                print(f"[CROSS-SOURCE RECOVERY] Backfilled '{f}' from alternate source: '{sec_val}'")
            elif is_curr_invalid and is_sec_valid and not safe_cross_source_field:
                print(f"[CROSS-SOURCE RECOVERY] Ignored alternate {f}: identity does not match the selected card.")
            # Upgrade fragmented name if secondary source has fewer spaces and matches same letters
            elif f == "name" and curr_val and sec_val:
                curr_clean = re.sub(r"\s+", "", curr_val).lower()
                sec_clean = re.sub(r"\s+", "", sec_val).lower()
                if curr_clean == sec_clean and len(sec_val.split()) < len(curr_val.split()):
                    print(f"[CROSS-SOURCE RECOVERY] Upgraded 'name' from cleaner alternate source: '{sec_val}' (was '{curr_val}')")
                    data["name"] = sec_val
            # Upgrade address if current has lowercase state code but secondary has uppercase
            elif f == "address" and curr_val and sec_val:
                if re.search(r"\b[a-z]{2}\s+(?:USA|US|\d{5})\b", curr_val) and re.search(r"\b[A-Z]{2}\s+(?:USA|US|\d{5})\b", sec_val):
                    print(f"[CROSS-SOURCE RECOVERY] Upgraded 'address' from cleaner alternate source: '{sec_val}' (was '{curr_val}')")
                    data["address"] = sec_val

    # 4. Comprehensive Quality & Integrity Checks
    missing_fields = [f for f in REQUIRED_FIELDS if not data.get(f) or not str(data.get(f)).strip()]
    
    # Check if contact is missing second phone number (must NOT trigger on URL slashes e.g. https://)
    raw_contact_phones = re.findall(r"\(?\d{3}\)?[- .\s]?\d{3}[- .\s]?\d{4}", combined_raw_text)
    curr_contact_phones = re.findall(r"\(?\d{3}\)?[- .\s]?\d{3}[- .\s]?\d{4}", str(data.get("office_contact", "")))
    has_slash_phone = bool(re.search(r"\d\)?\s*/\s*\(?\d", combined_raw_text)) and "/" not in str(data.get("office_contact", ""))
    has_contact_truncation = (len(raw_contact_phones) >= 2 and len(curr_contact_phones) < 2) or has_slash_phone
    
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
    data = apply_star_delimited_fields(data, combined_raw_text)
    data = refine_extracted_data(data, combined_raw_text)
    data = sanitize_company_and_website(data)
    data["designation"] = normalize_designation_punctuation(data.get("designation", ""))

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


def sleep_with_countdown(seconds: int, message: str = "Waiting", allow_skip: bool = False) -> str | None:
    """Displays a countdown and returns ``skip`` or ``admin_verified`` on operator action."""
    for remaining in range(seconds, 0, -1):
        mins, secs = divmod(remaining, 60)
        hint = " (S: skip, P: submit + admin-verify)" if allow_skip else ""
        sys.stdout.write(f"\r{message}: {mins:02d}m {secs:02d}s remaining...{hint} ")
        sys.stdout.flush()
        # Poll in small intervals so a skip command is acted on immediately.
        for _ in range(10):
            if allow_skip and msvcrt and msvcrt.kbhit():
                key = msvcrt.getwch().lower()
                if key in ("s", "p"):
                    # Consume Enter if it was typed after S, without blocking.
                    if msvcrt.kbhit():
                        msvcrt.getwch()
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    return "skip" if key == "s" else "admin_verified"
            time.sleep(0.1)
    sys.stdout.write(f"\r{message}: Time completed! {' ' * 20}\n")
    sys.stdout.flush()
    return False


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


def prompt_settings(
    fill_unfilled_first: bool = None,
    auto_mode: bool = False,
    start_qr_override: int = None,
    gap_override: str = None,
    batch_override: str = None,
    break_override: str = None
):
    """Setup before running the automation (supports interactive prompt or auto_mode)."""
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

    if auto_mode:
        start_qr = max(1, start_qr_override) if start_qr_override is not None else next_qr
        min_gap, max_gap = parse_range(gap_override, 45, 75) if gap_override else (45, 75)
        if min_gap > max_gap: min_gap, max_gap = max_gap, min_gap
        min_batch, max_batch = parse_range(batch_override, 35, 48) if batch_override else (35, 48)
        if min_batch > max_batch: min_batch, max_batch = max_batch, min_batch
        min_break_min, max_break_min = parse_range(break_override, 10, 17) if break_override else (10, 17)
        if min_break_min > max_break_min: min_break_min, max_break_min = max_break_min, min_break_min
        fill_unfilled_first = bool(fill_unfilled_first)

        print("\n" + "-" * 65)
        print(f"[AUTO-CONFIG] Fill Unfilled First:  {'YES' if fill_unfilled_first else 'NO'}")
        print(f"[AUTO-CONFIG] Delay on Screen:      {min_gap} to {max_gap} seconds")
        print(f"[AUTO-CONFIG] Forms Per Batch:      {min_batch} to {max_batch}")
        print(f"[AUTO-CONFIG] Batch Break:          {min_break_min} to {max_break_min} minutes")
        print(f"[AUTO-CONFIG] Automation Start:     QRCode - {start_qr}")
        print("=" * 65 + "\n")

        return {
            "min_gap": min_gap,
            "max_gap": max_gap,
            "min_batch": min_batch,
            "max_batch": max_batch,
            "min_break_sec": min_break_min * 60,
            "max_break_sec": max_break_min * 60,
            "start_qr": start_qr,
            "fill_unfilled_first": fill_unfilled_first
        }

    # Mode selection: if not provided by CLI flag, ask if there are unfilled forms
    if fill_unfilled_first is None:
        if total_unfilled > 0:
            print(f"[!] Found {total_unfilled} unfilled/skipped forms in database.")
            ans = input(f"[?] Fill unfilled previous forms first before next QR? (y/n) [Default: n]: ").strip().lower()
            fill_unfilled_first = ans in ("y", "yes")
        else:
            fill_unfilled_first = False

    # 1. Start QR selection
    start_input = input(f"[?] Enter the QR number to start from [Default: {next_qr}]: ").strip()
    try:
        start_qr = max(1, int(start_input)) if start_input else next_qr
    except ValueError:
        print(f"[!] Invalid QR number. Continuing from the next queued QR (QRCode - {next_qr}).")
        start_qr = next_qr

    # 2. Time gap between forms
    default_gap = "45-75"
    gap_input = input(f"[?] Enter inspection & wait time between forms in seconds (e.g. 45-75) [Default: {default_gap}s]: ")
    min_gap, max_gap = parse_range(gap_input, 45, 75)
    if min_gap > max_gap:
        min_gap, max_gap = max_gap, min_gap

    # 3. Forms per batch
    default_batch = "35-48"
    batch_input = input(f"[?] Enter how many forms to fill in a row before a break (e.g. 35-48) [Default: {default_batch}]: ")
    min_batch, max_batch = parse_range(batch_input, 35, 48)
    if min_batch > max_batch:
        min_batch, max_batch = max_batch, min_batch

    # 4. Break duration
    default_break = "10-17"
    break_input = input(f"[?] Enter break duration between batches in minutes (e.g. 10-17) [Default: {default_break} min]: ")
    min_break_min, max_break_min = parse_range(break_input, 10, 17)
    if min_break_min > max_break_min:
        min_break_min, max_break_min = max_break_min, min_break_min

    print("\n" + "-" * 65)
    print(f"[CONFIG] Fill Unfilled First:  {'YES (Will resolve unfilled forms first)' if fill_unfilled_first else 'NO (Normal queue)'}")
    print(f"[CONFIG] Human Review & Delay: {min_gap} to {max_gap} seconds on screen before submit")
    print(f"[CONFIG] Forms Per Batch:      {min_batch} to {max_batch} forms in a row")
    print(f"[CONFIG] Batch Break:          {min_break_min} to {max_break_min} minutes")
    print(f"[CONFIG] Automation Start:     QRCode - {start_qr}")
    print("=" * 65 + "\n")

    return {
        "min_gap": min_gap,
        "max_gap": max_gap,
        "min_batch": min_batch,
        "max_batch": max_batch,
        "min_break_sec": min_break_min * 60,
        "max_break_sec": max_break_min * 60,
        "start_qr": start_qr,
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

        print("[OK] Login form submitted. Waiting for redirect...")

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

        print("[OK] Successfully authenticated and arrived on task page!")

    except Exception as e:
        print(f"[!] Auto-login notice: {e}")
        print("    Navigating directly to task page...")
        try:
            driver.get(portal_url)
            time.sleep(3)
        except Exception:
            pass


def is_browser_session_error(exc: Exception) -> bool:
    """Whether Chrome/ChromeDriver disconnected and the current session is unusable."""
    message = str(exc).lower()
    return any(marker in message for marker in (
        "invalid session id", "session deleted", "not connected to devtools",
        "chrome not reachable", "disconnected:"
    ))


def start_portal_browser(options, portal_url: str):
    """Launch a fresh Chrome session and return it on the portal task page."""
    import glob
    driver = None
    cached_drivers = glob.glob(os.path.expanduser("~/.wdm/drivers/chromedriver/win64/*/chromedriver-win64/chromedriver.exe"))
    if cached_drivers:
        cached_drivers.sort()
        try:
            driver = webdriver.Chrome(service=Service(cached_drivers[-1]), options=options)
            print("[OK] Chrome launched using cached driver.")
        except Exception as exc:
            print(f"[!] Cached ChromeDriver launch failed: {exc}")
    if driver is None:
        try:
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        except Exception:
            driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 30)
    print(f"[*] Navigating to {portal_url}")
    driver.get(portal_url)
    time.sleep(2)
    is_login_page = "login" in driver.current_url.lower() or bool(driver.find_elements(
        By.XPATH, "//input[@type='password'] | //input[@name='username']"
    ))
    if is_login_page:
        perform_portal_login(driver, portal_url)
    return driver, wait


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


def verify_pending_forms_during_break() -> int:
    """Automatically verify completed local records that have never been checked."""
    pending_qrs = get_unverified_completed_qrs()
    if not pending_qrs:
        print("[AUTO VERIFY] No previously submitted, unverified forms are waiting.")
        return 0

    print(f"[AUTO VERIFY] Starting cross-check of {len(pending_qrs)} previously submitted form(s)...")
    try:
        import verify_engine
        started, message = verify_engine.engine_instance.start_verification_async(qr_numbers=pending_qrs)
    except Exception as exc:
        print(f"[AUTO VERIFY] Could not load the verification engine: {exc}")
        return 0
    if not started:
        print(f"[AUTO VERIFY] Could not start: {message}")
        return 0

    while True:
        status = verify_engine.engine_instance.get_status()
        if not status.get("running"):
            break
        current = status.get("current_label") or status.get("message") or "Working..."
        print(f"\r[AUTO VERIFY] {status.get('processed', 0)}/{status.get('total', len(pending_qrs))} — {current}   ", end="", flush=True)
        time.sleep(2)

    status = verify_engine.engine_instance.get_status()
    print(f"\n[AUTO VERIFY] {status.get('message', 'Verification finished.')}")
    if status.get("errors"):
        print(f"[AUTO VERIFY] Errors: {'; '.join(status['errors'])}")
    return int(status.get("processed", 0))


def take_batch_break(config: dict, forms_filled: int):
    """Runs pending verification during the configured rest between form batches."""
    break_duration = random.randint(config["min_break_sec"], config["max_break_sec"])
    break_mins = round(break_duration / 60, 1)
    print("\n" + "=" * 65)
    print(f"[BATCH COMPLETED] Filled {forms_filled} forms in this row.")
    print(f"[LONG BREAK] Taking a rest of {break_mins} minutes before next batch...")
    print("=" * 65)
    break_started = time.monotonic()
    verify_pending_forms_during_break()
    remaining_break = max(0, break_duration - int(time.monotonic() - break_started))
    if remaining_break:
        print("[BATCH BREAK] Verification finished; completing the remaining break time.")
        sleep_with_countdown(remaining_break, message="[BATCH BREAK]")


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
                # USER PROTOCOL: "If any failure occurs, first mark it as failure occured in database. Then do with langchain"
                fail_reason = f"Missing fields on attempt {attempt}: {', '.join(missing_fields)}"
                mark_failure_in_db(
                    current_qr,
                    reason=fail_reason,
                    missing_fields=missing_fields,
                    raw_data=data,
                    status="failure_occurred_langchain_pending"
                )
                print("\n" + "=" * 70)
                print(f"[AUDIT PROTOCOL] Failure recorded in DB for {qr_label} (status='failure_occurred_langchain_pending').")
                print(f"[AUDIT PROTOCOL] Launching LangChain Multi-Model Ensemble Recovery...")
                print("=" * 70)

                lc_data, lc_diag = extract_with_langchain_ensemble(full_ocr_text, max_models=5)
                if lc_data:
                    for f in REQUIRED_FIELDS:
                        if lc_data.get(f) and str(lc_data.get(f)).strip():
                            data[f] = lc_data[f]

                # Check if missing fields are now resolved
                missing_fields = [
                    f for f in REQUIRED_FIELDS
                    if not data.get(f) or not str(data.get(f)).strip()
                ]

                if not missing_fields:
                    print(f"\n[LANGCHAIN RECOVERY SUCCESS] All fields successfully resolved by LangChain consensus for {qr_label}!")
                    update_failure_status(current_qr, status="resolved_by_langchain", raw_data=data)
                else:
                    if attempt < max_attempts:
                        print(f"[*] Still missing {missing_fields} after LangChain attempt {attempt}. Retrying QR reload...")
                        time.sleep(2)
                        continue
                    else:
                        alert_beep()
                        reason_msg = f"Missing required fields after LangChain retry: {', '.join(missing_fields)}"
                        print("\n" + "!" * 70)
                        print(f"[WARNING / STILL MISSING AFTER RETRY] For {qr_label}!")
                        print(f"Empty/Missing fields: {missing_fields}")
                        print(f"Full OCR Text:\n    {full_ocr_text}")
                        print(f"[!] Updating {qr_label} in DB as 'unfilled_failed'...")
                        update_failure_status(current_qr, status="unfilled_failed", reason=reason_msg, raw_data=data)
                        print("!" * 70)
                        print(f"[*] Beep alert triggered. Waiting for 30 seconds before moving to next QR...")
                        sleep_with_countdown(30, message=f"[SKIPPED {qr_label} - MISSING DATA] Moving to next QR in")
                        return False

            # 4. Fill form inputs on screen
            print("\n[*] Autofilling inputs into the form...")
            data["office_contact"] = normalize_office_contact(data.get("office_contact", ""))
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
                fail_reason = f"Incomplete fields in browser DOM: {', '.join(empty_browser_fields)}"
                mark_failure_in_db(
                    current_qr,
                    reason=fail_reason,
                    missing_fields=empty_browser_fields,
                    raw_data=final_form_data,
                    status="failure_occurred_langchain_pending"
                )
                print(f"[AUDIT PROTOCOL] Incomplete DOM inputs logged in DB. Running LangChain re-fill...")
                lc_data, _ = extract_with_langchain_ensemble(full_ocr_text, max_models=5)
                if lc_data:
                    for ef in empty_browser_fields:
                        if lc_data.get(ef) and str(lc_data.get(ef)).strip():
                            final_form_data[ef] = lc_data[ef]
                            for fname, locators, _ in field_mappings:
                                if fname == ef:
                                    fill_field(driver, locators, lc_data[ef])

                empty_browser_fields = [fname for fname, locators, _ in field_mappings if not get_field_value(driver, locators)]
                if not empty_browser_fields:
                    print(f"[LANGCHAIN RECOVERY SUCCESS] Browser fields populated via LangChain!")
                    update_failure_status(current_qr, status="resolved_by_langchain", raw_data=final_form_data)
                elif attempt < max_attempts:
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
                    print(f"[!] Updating {qr_label} in DB as 'unfilled_failed'...")
                    update_failure_status(current_qr, status="unfilled_failed", reason=reason_msg, raw_data=final_form_data)
                    print("!" * 70)
                    print(f"[*] Beep alert triggered. Waiting for 30 seconds before moving to next QR...")
                    sleep_with_countdown(30, message=f"[SKIPPED {qr_label} - INCOMPLETE INPUT] Moving to next QR in")
                    return False

            if is_retry:
                print(f"[[OK]] Retry successful! All 7/7 fields confirmed populated on screen for {qr_label}.")
            else:
                print(f"[[OK]] All 7/7 fields confirmed populated on screen.")

            # 6. Human Review & Inspection Countdown (Form is filled on screen)
            wait_delay = random.randint(config["min_gap"], config["max_gap"])
            print(f"\n[HUMAN INSPECTION] Form is filled. Pausing {wait_delay}s so you can inspect before auto-submit.")
            print("[HUMAN INSPECTION] Type S to skip, or P to submit and mark this QR Verified by Admin.")
            inspection_action = sleep_with_countdown(wait_delay, message=f"[SUBMIT TIMER] Submitting {qr_label} in", allow_skip=True)
            if inspection_action == "skip":
                save_unfilled_record(
                    current_qr,
                    reason="Skipped manually by operator during human inspection before submission.",
                    missing_fields=[],
                    raw_data=final_form_data,
                    status="skipped_by_user"
                )
                print(f"[SKIPPED BY USER] {qr_label} was not submitted and is recorded in Unfilled Forms.")
                return False

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
            final_form_data["office_contact"] = normalize_office_contact(final_form_data.get("office_contact", ""))
            save_qr_record(current_qr, final_form_data)
            if inspection_action == "admin_verified":
                mark_admin_verified(current_qr)
                print(f"[ADMIN VERIFIED] {qr_label} was submitted, saved, and excluded from future verification runs.")
            return True

        except Exception as qr_err:
            # Let the outer loop relaunch Chrome; this is not a data-extraction failure.
            if is_browser_session_error(qr_err):
                raise
            err_msg = str(qr_err)
            mark_failure_in_db(
                current_qr,
                reason=f"Processing error on attempt {attempt}: {err_msg}",
                missing_fields=["error"],
                raw_data=None,
                status="failure_occurred_langchain_pending"
            )
            if attempt < max_attempts:
                print("\n" + "!" * 70)
                print(f"[ERROR ON ATTEMPT {attempt}] Error for {qr_label}: {qr_err}")
                print(f"[*] Doing once again the same QR ({qr_label}) to try to get the data...")
                print("!" * 70)
                time.sleep(2)
                continue
            else:
                alert_beep()
                print("\n" + "!" * 70)
                print(f"[ERROR OCCURRED AFTER RETRY] Error during processing for {qr_label}: {err_msg}")
                print(f"[!] Updating {qr_label} in DB as 'unfilled_failed'...")
                update_failure_status(current_qr, status="unfilled_failed", reason=f"Error after retry: {err_msg}")
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

    portal_url = "https://zendataprotsk.live/start-task"
    print("[*] Starting Chrome Browser...")
    driver, wait = start_portal_browser(options, portal_url)

    forms_in_current_batch = 0
    target_batch_size = random.randint(config["min_batch"], config["max_batch"])

    try:
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
                print("  [[OK]] COMPLETED ATTEMPTING ALL PREVIOUS UNFILLED FORMS!")
                print("  Now seamlessly continuing to the next QR in queue...")
                print("=" * 65 + "\n")
            else:
                print("\n[*] No pending unfilled forms found in database. Continuing to next QR in queue.\n")

        # -------------------------------------------------------------------------
        # PHASE 2: CONTINUE NORMAL CONTINUOUS QR LOOP
        # -------------------------------------------------------------------------
        current_qr = config["start_qr"]

        print(f"\n[*] Continuing normal automation queue starting from QRCode - {current_qr} up to QRCode - {max_total_qrs}...\n")

        session_restarts = 0
        while current_qr <= max_total_qrs:
            qr_label = f"QRCode - {current_qr}"
            print(f"\n{'='*65}")
            print(f"[*] Processing: {qr_label} (Batch progress: {forms_in_current_batch + 1}/{target_batch_size})")
            print(f"{'='*65}")

            try:
                success = process_single_qr(driver, current_qr, config, wait)
                session_restarts = 0
            except Exception as exc:
                if not is_browser_session_error(exc) or session_restarts >= 2:
                    raise
                session_restarts += 1
                print(f"[BROWSER RECOVERY] Chrome disconnected while processing {qr_label}. Relaunching ({session_restarts}/2) and retrying the same QR...")
                try:
                    driver.quit()
                except Exception:
                    pass
                driver, wait = start_portal_browser(options, portal_url)
                continue
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
    parser.add_argument("--auto", action="store_true", help="Run non-interactively without prompting for input (for automated/agent execution)")
    parser.add_argument("--start-qr", type=int, default=None, help="QR number to start processing from")
    parser.add_argument("--gap", type=str, default=None, help="Wait / review gap in seconds (e.g. 45-75 or 15)")
    parser.add_argument("--batch", type=str, default=None, help="Forms per batch before break (e.g. 22-35)")
    parser.add_argument("--break-min", type=str, default=None, help="Break time between batches in minutes (e.g. 15-45)")
    parser.add_argument("--max-qrs", type=int, default=1200, help="Maximum total QRs to process (default 1200)")
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
        cfg = prompt_settings(
            fill_unfilled_first=True if args.fill_unfilled_first else None,
            auto_mode=args.auto,
            start_qr_override=args.start_qr,
            gap_override=args.gap,
            batch_override=args.batch,
            break_override=args.break_min
        )
        run_continuous_automation(cfg, max_total_qrs=args.max_qrs)
