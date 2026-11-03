"""Run dashboard-requested corrections in a visible portal browser session."""

import os
import re
import threading
import time
import uuid

from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

import db_manager


load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
PORTAL_EMAIL = (os.getenv("email") or os.getenv("PORTAL_EMAIL") or os.getenv("username") or "").strip()
PORTAL_PASSWORD = (os.getenv("password") or os.getenv("PORTAL_PASSWORD") or "").strip()

FIELDS = {
    "name": ["//input[@name='name']", "//input[@placeholder='Name']", "//label[contains(text(),'Name')]/following::input[1]"],
    "designation": ["//input[@name='designation']", "//input[@placeholder='Designation']", "//label[contains(text(),'Designation')]/following::input[1]"],
    "company": ["//input[@name='company_name']", "//input[@placeholder='Company Name']", "//label[contains(text(),'Company')]/following::input[1]"],
    "website": ["//input[@name='website']", "//input[@placeholder='Website']", "//label[contains(text(),'Website')]/following::input[1]"],
    "address": ["//input[@name='address']", "//input[@placeholder='Address']", "//label[contains(text(),'Address')]/following::input[1]"],
    "email": ["//input[@name='email']", "//input[@placeholder='Email']", "//label[contains(text(),'Email')]/following::input[1]"],
    "office_contact": ["//input[@name='office_contact']", "//input[@placeholder='Office Contact']", "//label[contains(text(),'Contact')]/following::input[1]"],
}

_lock = threading.Lock()
_jobs = {}
_active_drivers = {}


def _set_job(job_id, **values):
    with _lock:
        _jobs[job_id].update(values)


def get_job(job_id):
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def start_fix(qr_number, form_data):
    """Queue an edited form submission and return its dashboard polling ID."""
    normalized = {key: str(form_data.get(key) or "").strip() for key in FIELDS}
    missing = [key for key, value in normalized.items() if not value]
    if missing:
        return None, f"Complete all required fields: {', '.join(missing)}"
    if not PORTAL_EMAIL or not PORTAL_PASSWORD:
        return None, "Portal credentials were not found in the project's .env file."

    job_id = uuid.uuid4().hex
    with _lock:
        if any(job.get("running") for job in _jobs.values()):
            return None, "Another dashboard correction is already running. Wait for it to finish first."
        _jobs[job_id] = {
            "job_id": job_id,
            "qr_number": int(qr_number),
            "state": "queued",
            "running": True,
            "success": False,
            "submitted": False,
            "message": "Queued portal correction.",
        }

    thread = threading.Thread(target=_run_fix, args=(job_id, int(qr_number), normalized), daemon=True)
    thread.start()
    return job_id, "Portal correction started in a new browser window."


def _run_fix(job_id, qr_number, form_data):
    driver = None
    try:
        _set_job(job_id, state="opening", message="Opening a visible Chrome window...")
        options = webdriver.ChromeOptions()
        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        with _lock:
            _active_drivers[job_id] = driver

        wait = WebDriverWait(driver, 30)
        task_url = "https://zendataprotsk.live/start-task"
        _set_job(job_id, state="login", message="Opening the portal and signing in...")
        driver.get(task_url)

        if "login" in driver.current_url.lower() or driver.find_elements(By.XPATH, "//input[@type='password']"):
            username = wait.until(EC.presence_of_element_located((
                By.XPATH,
                "//input[@name='username' or @id='username' or @name='email' or @id='email' or @type='email']"
            )))
            password = wait.until(EC.presence_of_element_located((
                By.XPATH, "//input[@type='password' or @name='password' or @id='password']"
            )))
            username.clear()
            username.send_keys(PORTAL_EMAIL)
            password.clear()
            password.send_keys(PORTAL_PASSWORD)
            submit_login = driver.find_element(By.XPATH, "//form[@id='login_frm']//button[@type='submit'] | //button[@type='submit']")
            driver.execute_script("arguments[0].click();", submit_login)
            wait.until(lambda current: "login" not in current.current_url.lower())

        driver.get(task_url)
        dropdown = wait.until(EC.presence_of_element_located((By.XPATH, "//select[@id='select_data' or @name='select_data']")))
        qr_label = f"QRCode - {qr_number}"
        _set_job(job_id, state="loading_form", message=f"Loading {qr_label} in the portal...")
        qr_select = Select(dropdown)
        try:
            qr_select.select_by_visible_text(qr_label)
        except Exception:
            option = next((item for item in qr_select.options if re.search(rf"\b{qr_number}\b", item.text)), None)
            if option is None:
                raise RuntimeError(f"{qr_label} is not available in the portal's form list.")
            qr_select.select_by_value(option.get_attribute("value"))
        driver.execute_script("arguments[0].dispatchEvent(new Event('change', {bubbles: true}));", dropdown)

        _set_job(job_id, state="filling", message=f"Filling the edited values for {qr_label}...")
        for field, locators in FIELDS.items():
            value = form_data[field]
            elements = []
            for locator in locators:
                elements = driver.find_elements(By.XPATH, locator)
                if elements:
                    break
            if not elements:
                raise RuntimeError(f"Could not find the portal field for {field.replace('_', ' ')}.")
            element = elements[0]
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            element.clear()
            element.send_keys(value)
            driver.execute_script(
                "arguments[0].dispatchEvent(new Event('input', {bubbles: true})); arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
                element,
            )
            if (element.get_attribute("value") or "").strip() != value:
                raise RuntimeError(f"The portal did not accept the edited {field.replace('_', ' ')} value.")

        _set_job(job_id, state="submitting", message=f"Submitting the corrected {qr_label}...")
        submit_selectors = [
            "//button[contains(normalize-space(), 'Generate QRCode')]",
            "//button[contains(., 'Generate')]",
            "//input[@value='Generate QRCode']",
        ]
        submit_button = None
        for selector in submit_selectors:
            for candidate in driver.find_elements(By.XPATH, selector):
                if candidate.is_displayed() and candidate.is_enabled():
                    submit_button = candidate
                    break
            if submit_button:
                break
        if not submit_button:
            raise RuntimeError("Could not find the portal's Generate QRCode button.")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", submit_button)
        driver.execute_script("arguments[0].click();", submit_button)
        if not _wait_for_submission_confirmation(driver):
            raise RuntimeError("The portal did not show its submission confirmation. Check the open browser before retrying.")

        _set_job(
            job_id,
            state="saving_local",
            message="Portal accepted the corrected form. Saving it locally and refreshing verification...",
            success=True,
            submitted=True,
        )
        db_manager.save_qr_record(qr_number, form_data)
        _set_job(
            job_id,
            state="refreshing_verification",
            message="Portal submission succeeded. Refreshing the verification comparison...",
            success=True,
        )
        _refresh_verification(qr_number)
        _set_job(
            job_id,
            state="complete",
            running=False,
            success=True,
            message=f"{qr_label} was submitted. The browser window is left open for review.",
        )
    except Exception as exc:
        _set_job(job_id, state="failed", running=False, success=False, message=str(exc))
        # Keep a browser that reached the portal open so the user can inspect or
        # complete a login/form challenge manually.


def _wait_for_submission_confirmation(driver):
    """Wait for portal confirmation and leave it open for the user to inspect."""
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            alert = driver.switch_to.alert
        except Exception:
            alert = None
        if alert:
            message = alert.text
            if any(word in message.lower() for word in ("error", "failed", "invalid", "required")):
                raise RuntimeError(f"Portal rejected the corrected form: {message}")
            return True

        selectors = [
            "//div[contains(@class,'swal2-popup') and not(contains(@style, 'display: none'))]",
            "//div[contains(@class,'modal') and contains(@class,'show')]",
        ]
        for selector in selectors:
            for popup in driver.find_elements(By.XPATH, selector):
                if not popup.is_displayed():
                    continue
                message = popup.text
                if any(word in message.lower() for word in ("error", "failed", "invalid", "required")):
                    raise RuntimeError(f"Portal rejected the corrected form: {message}")
                return True
        time.sleep(0.4)
    return False


def _refresh_verification(qr_number):
    """Re-run the comparison for this corrected QR after the visible session submits."""
    import verify_engine

    engine = verify_engine.engine_instance
    while engine.get_status().get("running"):
        time.sleep(1)
    started, message = engine.start_verification_async(qr_numbers=[qr_number])
    if not started:
        raise RuntimeError(f"Portal submission succeeded, but verification refresh could not start: {message}")
    while engine.get_status().get("running"):
        time.sleep(1)
    status = engine.get_status()
    if status.get("errors"):
        raise RuntimeError(f"Portal submission succeeded, but verification refresh failed: {'; '.join(status['errors'])}")
    last_verified = status.get("last_verified") or {}
    if last_verified.get("qr_label") != f"QRCode - {qr_number}":
        raise RuntimeError("Portal submission succeeded, but the updated QR could not be re-verified.")
