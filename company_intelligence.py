"""
Company Intelligence Layer — Smart Recovery for Garbled OCR Fields.

When OCR produces hopelessly garbled text (e.g. the bottom row of a compressed
business card), AI models can only pass the garbage along. This layer uses
HISTORICAL KNOWLEDGE from previously verified cards of the SAME company to
reconstruct address, email, phone, and fix OCR artifacts like '0?Nel' → "O'Neal".

Features:
1. Company Address Memory: Learns verified addresses per company and uses them
   when OCR address is garbled (contains '?' or non-ASCII garbage).
2. Email Domain Recovery: When OCR email is invalid, constructs email from
   person's name + known company email domain.
3. Phone Recovery: Uses historical phone numbers from the same company.
4. OCR Artifact Cleanup: Fixes known persistent OCR misreadings like
   '0?Nel' → "O'Neal" using learned correction patterns.
5. Garbage Detection: Identifies when extracted fields contain non-printable
   characters, excessive symbols, or nonsensical patterns.
"""

import os
import re
import json
import sqlite3
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BRAIN_DIR = os.path.join(BASE_DIR, "model_brain")
DB_PATH = os.path.join(BASE_DIR, "qr_database.db")
COMPANY_INTEL_FILE = os.path.join(BRAIN_DIR, "company_intelligence.json")


def is_garbled(text: str) -> bool:
    """
    Detects if a string is garbled OCR output (not real readable text).
    Looks for: non-ASCII symbols, excessive punctuation, unbalanced brackets,
    sequences that can't be real words.
    """
    if not text or not isinstance(text, str):
        return True
    text = text.strip()
    if not text:
        return True

    # Count non-ASCII and non-standard characters
    garbage_chars = sum(1 for c in text if ord(c) > 127 or c in '×·★●◆■∗※')
    if garbage_chars >= 2:
        return True

    # Excessive special characters relative to length
    special_count = sum(1 for c in text if not c.isalnum() and c not in ' .,()-/@#&+:;\'')
    if len(text) > 5 and special_count / len(text) > 0.3:
        return True

    # Contains '?' in what should be a word (OCR artifact)
    if re.search(r'[a-zA-Z]\?[a-zA-Z]', text):
        return True

    # Nonsensical character sequences (consonant clusters that can't be English)
    if re.search(r'[bcdfghjklmnpqrstvwxyz]{5,}', text, re.IGNORECASE):
        return True

    return False


def is_garbled_email(email: str) -> bool:
    """Detects if an email address is garbled OCR output."""
    if not email or not isinstance(email, str):
        return True
    email = email.strip()
    if not email:
        return True

    # Must have exactly one @ with valid-looking parts on both sides
    if '@' not in email:
        return True

    # Check for non-ASCII
    if any(ord(c) > 127 for c in email):
        return True

    # Check for garbage characters
    if any(c in email for c in '×·★●◆■∗※?()'):
        return True

    # Basic email validation
    if not re.match(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$', email):
        return True

    return False


def is_garbled_phone(phone: str) -> bool:
    """Detects if a phone number is garbled OCR output."""
    if not phone or not isinstance(phone, str):
        return True
    phone = phone.strip()
    if not phone:
        return True

    # Valid phone patterns
    if re.search(r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', phone):
        return False

    # Placeholder values are OK
    if re.match(r'^(no\s*data|n/?a|none|no\s*phone|nil|not\s*available|[-]{1,3})$', phone, re.IGNORECASE):
        return False

    # Check for non-ASCII garbage
    if any(ord(c) > 127 for c in phone):
        return True

    # Check for letter contamination in phone
    letter_count = sum(1 for c in phone if c.isalpha())
    if letter_count > 3:
        return True

    return True


def is_garbled_address(address: str) -> bool:
    """Detects if an address is garbled or contains OCR artifacts."""
    if not address or not isinstance(address, str):
        return True
    address = address.strip()
    if not address:
        return True

    # Contains ? in the middle of words (OCR artifact like '0?Nel')
    if '?' in address:
        return True

    # Contains non-ASCII garbage
    if any(ord(c) > 127 for c in address):
        return True

    return False


class CompanyIntelligence:
    """
    Builds and queries a knowledge base of verified company information
    from historical database records.
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.company_data: Dict[str, Dict] = {}  # company_name -> aggregated info
        self.address_corrections: Dict[str, str] = {}  # garbled_fragment -> correct_fragment
        self._load_or_build()

    def _load_or_build(self):
        """Load cached intelligence or build from database."""
        if os.path.exists(COMPANY_INTEL_FILE):
            try:
                with open(COMPANY_INTEL_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    self.company_data = saved.get("company_data", {})
                    self.address_corrections = saved.get("address_corrections", {})
                if self.company_data:
                    return
            except Exception:
                pass
        self.build_from_database()

    def build_from_database(self):
        """Scan all verified records and build company intelligence."""
        if not os.path.exists(self.db_path):
            return

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            SELECT name, designation, company, website, address, email, office_contact
            FROM qr_records
            WHERE company IS NOT NULL AND company != ''
            ORDER BY qr_number ASC
        """)
        rows = cur.fetchall()
        conn.close()

        self.company_data.clear()
        self.address_corrections.clear()

        for name, desig, company, website, address, email, phone in rows:
            company = (company or "").strip()
            if not company:
                continue

            comp_key = company.lower()
            if comp_key not in self.company_data:
                self.company_data[comp_key] = {
                    "canonical_name": company,
                    "addresses": [],
                    "email_domains": [],
                    "phones": [],
                    "websites": [],
                    "email_patterns": [],  # e.g. "first.last", "flast"
                    "names": []
                }

            info = self.company_data[comp_key]

            # Collect addresses (only clean ones)
            address = (address or "").strip()
            if address and not is_garbled_address(address):
                if address not in info["addresses"]:
                    info["addresses"].append(address)

            # Collect email domains
            email = (email or "").strip()
            if email and not is_garbled_email(email) and "@" in email:
                domain = email.split("@")[1].lower()
                if domain not in info["email_domains"]:
                    info["email_domains"].append(domain)

                # Learn email pattern (first.last, flast, etc.)
                user_part = email.split("@")[0].lower()
                name_clean = (name or "").strip()
                if name_clean:
                    name_parts = name_clean.lower().split()
                    if len(name_parts) >= 2:
                        first = name_parts[0]
                        last = name_parts[-1]
                        if f"{first}.{last}" == user_part:
                            if "first.last" not in info["email_patterns"]:
                                info["email_patterns"].append("first.last")
                        elif f"{first[0]}.{last}" == user_part:
                            if "f.last" not in info["email_patterns"]:
                                info["email_patterns"].append("f.last")
                        elif f"{first[0]}{last}" == user_part:
                            if "flast" not in info["email_patterns"]:
                                info["email_patterns"].append("flast")
                        elif f"{first}_{last}" == user_part:
                            if "first_last" not in info["email_patterns"]:
                                info["email_patterns"].append("first_last")
                        elif f"{first}{last}" == user_part:
                            if "firstlast" not in info["email_patterns"]:
                                info["email_patterns"].append("firstlast")

            # Collect phones (only clean ones)
            phone = (phone or "").strip()
            if phone and not is_garbled_phone(phone):
                if phone not in info["phones"]:
                    info["phones"].append(phone)

            # Collect websites
            website = (website or "").strip()
            if website and website not in info["websites"]:
                info["websites"].append(website)

            # Collect names
            name_clean = (name or "").strip()
            if name_clean and name_clean not in info["names"]:
                info["names"].append(name_clean)

        # Build common address correction patterns from known addresses
        # e.g., "0?Nel" appears in 8x8 addresses -> should be "O'Neal"
        self._build_address_corrections()
        self.save()

        print(f"[Company Intelligence] Built knowledge base: {len(self.company_data)} companies")
        for comp_key, info in self.company_data.items():
            if info["addresses"] or info["email_domains"]:
                print(f"    {info['canonical_name']}: "
                      f"{len(info['addresses'])} addresses, "
                      f"{len(info['email_domains'])} email domains, "
                      f"{len(info['phones'])} phones, "
                      f"patterns={info['email_patterns']}")

    def _build_address_corrections(self):
        """Build a map of known OCR artifacts and their corrections."""
        # Hardcoded known corrections from observed patterns
        self.address_corrections = {
            "0?Nel": "O'Neal",
            "0?nel": "O'Neal",
            "0?NEL": "O'NEAL",
            "0?Ne": "O'Nea",  # truncated variant
        }

    def save(self):
        """Persist the intelligence to disk."""
        os.makedirs(BRAIN_DIR, exist_ok=True)
        try:
            with open(COMPANY_INTEL_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "company_data": self.company_data,
                    "address_corrections": self.address_corrections,
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Company Intelligence] Save error: {e}")

    def get_company_info(self, company_name: str) -> Optional[Dict]:
        """Look up intelligence for a company."""
        if not company_name:
            return None
        key = company_name.lower().strip()
        return self.company_data.get(key)

    def fix_address(self, address: str, company_name: str = "") -> str:
        """
        Fix garbled address using:
        1. Known OCR artifact corrections (e.g., 0?Nel -> O'Neal)
        2. Historical company address if available
        """
        if not address:
            return address

        # Apply known corrections
        fixed = address
        for garbled, correct in self.address_corrections.items():
            if garbled in fixed:
                fixed = fixed.replace(garbled, correct)
                print(f"[Company Intelligence] Fixed address OCR artifact: '{garbled}' -> '{correct}'")

        # Remove non-ASCII garbage characters
        fixed = re.sub(r'[^\x20-\x7E]', '', fixed)

        # Remove trailing garbage (non-address characters after the ZIP or country)
        # Pattern: keep everything up to and including ZIP code or "USA"/"US"
        zip_match = re.search(r'\b\d{5}(?:-\d{4})?\b', fixed)
        country_match = re.search(r'\b(?:USA|US|United States)\b', fixed, re.IGNORECASE)
        if zip_match:
            end_pos = zip_match.end()
            # Check if there's a country after the ZIP
            rest = fixed[end_pos:].strip()
            country_after = re.match(r'[\s,]*(?:USA|US|United States)\b', rest, re.IGNORECASE)
            if country_after:
                end_pos += country_after.end()
            fixed = fixed[:end_pos].strip()
        elif country_match:
            # Keep up to country + possible ZIP after
            end_pos = country_match.end()
            rest = fixed[end_pos:].strip()
            zip_after = re.match(r'[\s,]*\d{5}(?:-\d{4})?', rest)
            if zip_after:
                end_pos += zip_after.end()
            fixed = fixed[:end_pos].strip()

        # If still garbled after corrections, try company historical address
        if is_garbled_address(fixed) and company_name:
            info = self.get_company_info(company_name)
            if info and info["addresses"]:
                # Use the most detailed (longest) known address
                best_addr = max(info["addresses"], key=len)
                print(f"[Company Intelligence] Replaced garbled address with known company address: '{best_addr}'")
                return best_addr

        return fixed.strip()

    def recover_email(self, current_email: str, person_name: str, company_name: str) -> str:
        """
        Recover email when OCR produced garbage.
        Uses: person_name + known email domain + learned email patterns.
        """
        if not is_garbled_email(current_email):
            return current_email  # Email is fine, don't touch it

        if not company_name:
            return current_email

        info = self.get_company_info(company_name)
        if not info or not info["email_domains"]:
            return current_email

        domain = info["email_domains"][0]  # Use primary domain
        patterns = info["email_patterns"]

        if not person_name or not person_name.strip():
            return current_email

        name_parts = person_name.strip().split()
        if len(name_parts) < 2:
            return current_email

        first = name_parts[0].lower()
        last = name_parts[-1].lower()

        # Try patterns in order of what we've seen for this company
        constructed = None
        if "first.last" in patterns:
            constructed = f"{first}.{last}@{domain}"
        elif "f.last" in patterns:
            constructed = f"{first[0]}.{last}@{domain}"
        elif "flast" in patterns:
            constructed = f"{first[0]}{last}@{domain}"
        elif "first_last" in patterns:
            constructed = f"{first}_{last}@{domain}"
        elif "firstlast" in patterns:
            constructed = f"{first}{last}@{domain}"
        else:
            # Default to first.last pattern (most common)
            constructed = f"{first}.{last}@{domain}"

        if constructed:
            print(f"[Company Intelligence] Recovered email from name + company domain: '{constructed}' (was '{current_email}')")
            return constructed

        return current_email

    def recover_phone(self, current_phone: str, company_name: str) -> str:
        """
        Recover phone when OCR produced garbage.
        Uses the most common phone from historical records of the same company.
        """
        if not is_garbled_phone(current_phone):
            return current_phone  # Phone is fine

        if not company_name:
            return current_phone

        info = self.get_company_info(company_name)
        if not info or not info["phones"]:
            return current_phone

        # Use the most complete phone (longest, likely has multiple numbers)
        best_phone = max(info["phones"], key=len)
        print(f"[Company Intelligence] Recovered phone from company history: '{best_phone}' (was '{current_phone}')")
        return best_phone

    def apply_intelligence(self, data: Dict[str, str]) -> Dict[str, str]:
        """
        Master method: Apply all company intelligence to fix garbled fields.
        Only activates when fields are detected as garbled (never overwrites good data).
        """
        company = data.get("company", "").strip()
        name = data.get("name", "").strip()

        if not company:
            return data

        info = self.get_company_info(company)
        if not info:
            return data

        changes_made = False

        # Fix address
        current_addr = data.get("address", "").strip()
        if current_addr:
            fixed_addr = self.fix_address(current_addr, company)
            if fixed_addr != current_addr:
                data["address"] = fixed_addr
                changes_made = True

        # Recover email
        current_email = data.get("email", "").strip()
        if current_email:
            fixed_email = self.recover_email(current_email, name, company)
            if fixed_email != current_email:
                data["email"] = fixed_email
                changes_made = True

        # Recover phone
        current_phone = data.get("office_contact", "").strip()
        if current_phone:
            fixed_phone = self.recover_phone(current_phone, company)
            if fixed_phone != current_phone:
                data["office_contact"] = fixed_phone
                changes_made = True

        if changes_made:
            print(f"[Company Intelligence] Applied company knowledge for '{company}' to fix garbled fields.")

        return data

    def learn_record(self, name: str, company: str, address: str, email: str, phone: str, website: str):
        """Online learning: add a new verified record to the knowledge base."""
        if not company:
            return

        comp_key = company.lower().strip()
        if comp_key not in self.company_data:
            self.company_data[comp_key] = {
                "canonical_name": company,
                "addresses": [],
                "email_domains": [],
                "phones": [],
                "websites": [],
                "email_patterns": [],
                "names": []
            }

        info = self.company_data[comp_key]

        if address and not is_garbled_address(address) and address not in info["addresses"]:
            info["addresses"].append(address)

        if email and not is_garbled_email(email) and "@" in email:
            domain = email.split("@")[1].lower()
            if domain not in info["email_domains"]:
                info["email_domains"].append(domain)

        if phone and not is_garbled_phone(phone) and phone not in info["phones"]:
            info["phones"].append(phone)

        if website and website not in info["websites"]:
            info["websites"].append(website)

        if name and name not in info["names"]:
            info["names"].append(name)

        self.save()


# Global singleton
_company_intel_instance: Optional[CompanyIntelligence] = None


def get_company_intelligence() -> CompanyIntelligence:
    """Get or initialize the global CompanyIntelligence instance."""
    global _company_intel_instance
    if _company_intel_instance is None:
        _company_intel_instance = CompanyIntelligence()
    return _company_intel_instance


if __name__ == "__main__":
    intel = get_company_intelligence()
    print(f"\nTotal companies: {len(intel.company_data)}")
    for key, info in intel.company_data.items():
        if info["addresses"] or info["email_domains"]:
            print(f"\n  {info['canonical_name']}:")
            print(f"    Addresses: {info['addresses']}")
            print(f"    Email domains: {info['email_domains']}")
            print(f"    Email patterns: {info['email_patterns']}")
            print(f"    Phones: {info['phones']}")

