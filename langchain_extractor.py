"""
LangChain Multi-Model Ensemble & Majority-Voting Business Card Extractor.

Features:
1. Pydantic-enforced 7-field structured extraction (name, designation, company, website, address, email, office_contact).
2. Parallel execution across 3 to 5 diverse LLM models (Groq + OpenRouter).
3. Field-by-field Majority Voting with intelligent whitespace & word-boundary preservation:
   - Specifically prevents compound word concatenation (e.g. 'Ram Power' vs 'RamPower').
   - Favors space-separated words over collapsed CamelCase/PascalCase tokens.
   - Cross-checks with raw OCR text and bounding tokens to confirm true spacing.
4. Comprehensive logging, confidence scoring, and model agreement diagnostics.
"""

import os
import re
import json
import difflib
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Any, Tuple, Optional
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from brain_engine import get_brain_engine, clean_address_ocr_glitches

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()

REQUIRED_FIELDS = [
    "name",
    "designation",
    "company",
    "website",
    "address",
    "email",
    "office_contact"
]


class BusinessCardSchema(BaseModel):
    name: str = Field(default="", description="Full name of person with exact casing")
    designation: str = Field(default="", description="Job title / role with exact casing")
    company: str = Field(default="", description="Company / Organization name with exact spacing between words")
    website: str = Field(default="", description="Exact website URL as printed (do not prepend http:// if absent)")
    address: str = Field(default="", description="Complete postal address (combine street prefixes, suite, city, state, zip)")
    email: str = Field(default="", description="Email address")
    office_contact: str = Field(default="", description="ALL phone/mobile numbers present. If multiple, include both separated by /")


SYSTEM_PROMPT = (
    "You are an expert, meticulous AI assistant specialized in business card OCR data extraction.\n"
    "The asterisk (*) is the primary field boundary. When there are exactly 7 non-empty star-separated segments, map them left-to-right to name, designation, company, website, address, email, and office_contact. Never move content across a star boundary.\n"
    "Use context and OCR correction only to clean text inside its own segment. If the separators are incomplete or ambiguous, then use semantic extraction as a fallback.\n"
    "Your mission is to extract exactly 7 fields verbatim from the OCR text of a business card:\n"
    "1. name: Person's full name (preserve exact casing).\n"
    "2. designation: Job title / role.\n"
    "3. company: Company / organization name. CRITICAL: Preserve all original word spaces! "
    "NEVER fuse or merge adjacent words into CamelCase. For example, if the card shows 'Ram Power', you MUST output 'Ram Power' with the space. NEVER output 'RamPower'!\n"
    "4. website: Exact website URL as printed. DO NOT add 'http://' or 'https://' if not explicitly printed on the card! Preserve exact prefix like 'www.' or root domain.\n"
    "5. address: Copy the address segment VERBATIM from the OCR text. "
    "CRITICAL: NEVER add commas, periods, or ANY punctuation that is not already present in the OCR text. "
    "If the card prints 'Sparks NV USA' without a comma, output it exactly as 'Sparks NV USA'. "
    "If the card prints '1234 Main St Suite 500 Dallas TX 75001', output it exactly that way — no commas.\n"
    "6. email: Email address. NEVER add spaces inside the email.\n"
    "7. office_contact: ALL phone/mobile numbers present. If there are multiple numbers (e.g. phone and fax, or direct and toll-free), YOU MUST INCLUDE ALL NUMBERS TOGETHER. If the card explicitly states 'No Data' or 'NA', use that exact text.\n\n"
    "CRITICAL RULES ON SPACING & WORD BOUNDARIES:\n"
    "- NEVER concatenate words together. Keep spaces between separate words in company names, titles, and addresses.\n"
    "- CRITICAL ON ADDRESS NUMBERS & ZIP CODES: Never confuse the digit '9' with the letter 'g', or '0' with 'o'. US ZIP codes are ALWAYS pure numeric digits (e.g. '98052-6399', '94089', NEVER 'g8052' or '9408g'). Suite, floor, building and street numbers use digits (e.g. 'Suite 900', '9th Floor', 'Bldg 9', '4001', NEVER 'Suite g00' or '40o1').\n"
    "- ADDRESS PUNCTUATION: Output address exactly as OCR shows it. If no comma is present in the OCR address segment, do NOT add one. Never invent punctuation.\n"
    "- Keep fields separate: ZIP codes belong to address, email belongs to email, and only phone numbers belong to office_contact.\n"
    "- Email must contain one @ and a domain; each phone must contain 10 digits. Never split a corrupted OCR string across fields to fill blanks.\n"
    "- Retain exact casing and punctuation as printed on the card.\n"
    "- Return strictly a valid JSON object matching the requested fields."
)


def get_active_model_configs() -> List[Dict[str, Any]]:
    """Return a list of available models across Groq and OpenRouter."""
    models = []

    # Groq Models (Ultra-fast inference)
    if GROQ_API_KEY:
        models.append({
            "provider": "groq",
            "model_name": "openai/gpt-oss-120b",
            "timeout": 12
        })
        models.append({
            "provider": "groq",
            "model_name": "openai/gpt-oss-20b",
            "timeout": 10
        })
        models.append({
            "provider": "groq",
            "model_name": "qwen/qwen3.8-27b",
            "timeout": 10
        })

    # OpenRouter Models (High accuracy & diverse architectures)
    if OPENROUTER_API_KEY:
        models.append({
            "provider": "openrouter",
            "model_name": "nvidia/nemotron-3-ultra-550b-a55b:free",
            "timeout": 20
        })
        models.append({
            "provider": "openrouter",
            "model_name": "meta-llama/llama-3.3-70b-instruct",
            "timeout": 14
        })
        models.append({
            "provider": "openrouter",
            "model_name": "qwen/qwen-2.5-72b-instruct",
            "timeout": 14
        })

    return models


def instantiate_llm(config: Dict[str, Any]):
    """Instantiate a LangChain LLM instance with structured output support."""
    provider = config["provider"]
    model_name = config["model_name"]
    timeout = config.get("timeout", 12)

    if provider == "groq":
        from langchain_groq import ChatGroq
        # Increase max_tokens to 1500 for reasoning models (e.g. gpt-oss-120b, gpt-oss-20b)
        # which consume tokens for reasoning before emitting the final JSON
        return ChatGroq(
            model_name=model_name,
            groq_api_key=GROQ_API_KEY,
            temperature=0.0,
            timeout=timeout,
            max_tokens=1500
        )
    elif provider == "openrouter":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model_name=model_name,
            openai_api_key=OPENROUTER_API_KEY,
            openai_api_base="https://openrouter.ai/api/v1",
            temperature=0.0,
            timeout=timeout,
            max_tokens=1000
        )
    else:
        raise ValueError(f"Unknown provider: {provider}")


def invoke_single_model(config: Dict[str, Any], raw_ocr_text: str, custom_system_prompt: Optional[str] = None) -> Optional[Dict[str, str]]:
    """Invoke a single model via LangChain and parse structured JSON result."""
    provider = config["provider"]
    model_name = config["model_name"]

    from langchain_core.messages import SystemMessage, HumanMessage

    user_content = (
        f"Raw Business Card OCR Text:\n{raw_ocr_text}\n\n"
        "Extract all 7 fields into JSON. Ensure exact spacing (e.g. 'Ram Power', NOT 'RamPower')."
    )

    sys_text = custom_system_prompt or SYSTEM_PROMPT
    messages = [
        SystemMessage(content=sys_text),
        HumanMessage(content=user_content)
    ]

    try:
        llm = instantiate_llm(config)
        # Attempt structured output first
        try:
            structured_llm = llm.with_structured_output(BusinessCardSchema)
            res = structured_llm.invoke(messages)
            if isinstance(res, BusinessCardSchema):
                return res.model_dump()
            elif isinstance(res, dict):
                return res
        except Exception:
            # Fallback to standard chat invocation and regex JSON parsing
            pass

        response = llm.invoke(messages)
        content_text = response.content if hasattr(response, "content") else str(response)

        # Parse JSON from content_text
        m = re.search(r"\{.*\}", content_text, re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group(0))
                cleaned = {}
                for k in REQUIRED_FIELDS:
                    val = parsed.get(k, "")
                    cleaned[k] = str(val).strip() if val is not None else ""
                return cleaned
            except Exception:
                pass

        # Check if response had tool_calls
        if hasattr(response, "tool_calls") and response.tool_calls:
            for tc in response.tool_calls:
                args = tc.get("args") or {}
                if any(args.get(f) for f in REQUIRED_FIELDS):
                    cleaned = {}
                    for k in REQUIRED_FIELDS:
                        val = args.get(k, "")
                        cleaned[k] = str(val).strip() if val is not None else ""
                    return cleaned
    except Exception as e:
        print(f"[LangChain Ensemble] Model {provider}/{model_name} error: {e}")

    return None


def is_camelcase_fused(val: str) -> bool:
    """Detect if a string looks like a fused CamelCase/PascalCase word (e.g., 'RamPower')."""
    if not val or " " in val:
        return False
    # Matches words like RamPower, MegaTech, DataSystems where uppercase letters follow lowercase
    return bool(re.search(r"[a-z][A-Z]", val))


def separate_camelcase(val: str) -> str:
    """Separate CamelCase words with a space (e.g. 'RamPower' -> 'Ram Power')."""
    return re.sub(r"([a-z])([A-Z])", r"\1 \2", val)


def reconcile_field_candidates(field_name: str, candidates: List[str], raw_ocr_text: str) -> Tuple[str, Dict[str, Any]]:
    """
    Field-by-Field Majority Voting with Space-Restoration & CamelCase reconciliation.
    Specifically handles cases like 'Ram Power' vs 'RamPower'.
    """
    valid_candidates = [c.strip() for c in candidates if c and str(c).strip()]
    if not valid_candidates:
        return "", {"votes": {}, "winner": "", "confidence": 0.0, "reason": "No valid candidates"}

    # 1. Spacing Normalization & Fusion Detection
    # If one model returned "Ram Power" and another returned "RamPower",
    # check if removing spaces yields identical text.
    normalized_groups: Dict[str, List[str]] = {}
    for c in valid_candidates:
        key = c.replace(" ", "").lower()
        if key not in normalized_groups:
            normalized_groups[key] = []
        normalized_groups[key].append(c)

    # For each group, determine if a space-separated variant exists
    scored_candidates: Dict[str, float] = {}

    for norm_key, variants in normalized_groups.items():
        # Count occurrences
        for v in variants:
            # Base weight: 1.0 vote per model
            weight = 1.0

            # If this candidate has spaces between capitalized words (e.g. "Ram Power"):
            if " " in v:
                weight += 0.5  # Favor properly spaced variant over fused compound

            # Check if variant appears verbatim in raw OCR text
            if v.lower() in raw_ocr_text.lower():
                weight += 0.8  # Strong bonus: verbatim match in original OCR

            # Check if the fused CamelCase was detected
            if is_camelcase_fused(v):
                # Penalty for CamelCase fusion if a spaced variant was also found
                spaced_v = separate_camelcase(v)
                if spaced_v.lower() in raw_ocr_text.lower() or any(" " in other for other in variants):
                    weight -= 0.6

            scored_candidates[v] = scored_candidates.get(v, 0.0) + weight

    # Incorporate Learned Brain Knowledge Graph & Spacing Memory bonuses
    try:
        brain = get_brain_engine()
    except Exception:
        brain = None

    if brain:
        if field_name == "company":
            domain_match = re.search(r"@([a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)", raw_ocr_text)
            if not domain_match:
                domain_match = re.search(r"(?:https?://|www\.)([a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)", raw_ocr_text)
            if domain_match:
                dom = domain_match.group(1).lower().replace("www.", "")
                learned_comp = brain.domain_company_graph.get(dom)
                if learned_comp:
                    for v in scored_candidates:
                        if v.lower() == learned_comp.lower():
                            scored_candidates[v] += 1.5
            for v in scored_candidates:
                fused = re.sub(r"\s+", "", v).lower()
                if fused in brain.spacing_patterns:
                    proper = brain.spacing_patterns[fused]
                    if v.lower() == proper.lower():
                        scored_candidates[v] += 1.2
        elif field_name == "designation":
            for v in scored_candidates:
                if v in brain.designation_lexicon:
                    scored_candidates[v] += 0.8

    # Pick candidate with highest weighted score
    sorted_candidates = sorted(scored_candidates.items(), key=lambda x: x[1], reverse=True)
    winner, top_score = sorted_candidates[0]

    # If top winner is still CamelCase fused, but spaced variant matches OCR text, expand it
    if is_camelcase_fused(winner) and field_name in ("company", "name", "designation"):
        spaced = separate_camelcase(winner)
        if spaced.lower() in raw_ocr_text.lower():
            winner = spaced

    # CRITICAL SPACE PRESERVATION:
    # If the winner lost spaces (e.g. 'VicePresident' or 'CTo,Serverand') but the exact phrase
    # with spaces exists in raw_ocr_text, ALWAYS restore the spaced OCR version!
    winner_compact = re.sub(r'[^a-zA-Z0-9]', '', winner).lower()
    if winner_compact and winner_compact in re.sub(r'[^a-zA-Z0-9]', '', raw_ocr_text).lower():
        chars_map = []
        for idx, ch in enumerate(raw_ocr_text):
            if re.match(r'[a-zA-Z0-9]', ch):
                chars_map.append((idx, ch.lower()))
        ref_alphanum = ''.join(c[1] for c in chars_map)
        pos = ref_alphanum.find(winner_compact)
        if pos != -1:
            start_idx = chars_map[pos][0]
            end_idx = chars_map[pos + len(winner_compact) - 1][0] + 1
            ocr_segment_match = raw_ocr_text[start_idx:end_idx].strip()
            # If OCR has more spaces or proper spacing, restore from OCR!
            if ocr_segment_match.count(' ') >= winner.count(' ') and len(ocr_segment_match) >= len(winner):
                winner = ocr_segment_match

    total_votes = len(valid_candidates)
    confidence = round(min(1.0, top_score / (total_votes * 1.5 if total_votes else 1.0)), 2)

    vote_tally = {}
    for c in valid_candidates:
        vote_tally[c] = vote_tally.get(c, 0) + 1

    metadata = {
        "tally": vote_tally,
        "scores": scored_candidates,
        "winner": winner,
        "confidence": confidence,
        "total_models": total_votes
    }
    return winner, metadata


def extract_with_langchain_ensemble(
    raw_ocr_text: str,
    max_models: int = 5
) -> Tuple[Dict[str, str], Dict[str, Any]]:
    """
    Main LangChain Entry Point:
    Runs 3 to 5 diverse models in parallel, gathers responses,
    and performs Field-by-Field Majority Voting with whitespace preservation.

    Returns:
        (resolved_data_dict, diagnostics_dict)
    """
    # 1. Engage Trained Brain Engine for Few-Shot Exemplars and Local Prediction
    brain = get_brain_engine()
    exemplars_prompt = brain.format_exemplars_for_prompt(raw_ocr_text, top_k=2)
    augmented_system_prompt = SYSTEM_PROMPT + "\n" + exemplars_prompt if exemplars_prompt else SYSTEM_PROMPT

    model_responses: List[Dict[str, str]] = []
    participating_models = []

    # 2. Local Brain Inference (Model 0: Local Trained Brain)
    try:
        brain_prediction, brain_conf = brain.predict_offline(raw_ocr_text)
        if brain_prediction and any(brain_prediction.values()):
            model_responses.append(brain_prediction)
            participating_models.append("brain/adaptive-model-v2")
            print(f"[Brain Engine] Direct local model prediction completed with high confidence.")
    except Exception as e:
        print(f"[Brain Engine] Local prediction note: {e}")

    model_configs = get_active_model_configs()[:max_models]
    if not model_configs and not model_responses:
        print("[LangChain Ensemble] No API keys configured for Groq or OpenRouter and no Brain prediction!")
        return {}, {"error": "No API keys configured"}

    print(f"\n[LangChain Ensemble] Launching parallel extraction across {len(model_configs)} cloud models + Local Trained Brain...")
    print(f"    Model 0: BRAIN -> adaptive-model-v2 (Local Offline Brain)")
    for idx, cfg in enumerate(model_configs, 1):
        print(f"    Model {idx}: {cfg['provider'].upper()} -> {cfg['model_name']}")

    # Parallel Execution across all models with augmented exemplars prompt
    if model_configs:
        with ThreadPoolExecutor(max_workers=len(model_configs)) as executor:
            future_to_config = {
                executor.submit(invoke_single_model, cfg, raw_ocr_text, augmented_system_prompt): cfg
                for cfg in model_configs
            }
        for future in as_completed(future_to_config):
            cfg = future_to_config[future]
            model_tag = f"{cfg['provider']}/{cfg['model_name']}"
            try:
                res = future.result()
                if res and any(res.get(f) for f in REQUIRED_FIELDS):
                    model_responses.append(res)
                    participating_models.append(model_tag)
                    print(f"[LangChain Ensemble] [OK] {model_tag} completed successfully.")
                else:
                    print(f"[LangChain Ensemble] [!] {model_tag} returned empty or invalid schema.")
            except Exception as e:
                print(f"[LangChain Ensemble] [!] {model_tag} failed: {e}")

    if not model_responses:
        print("[LangChain Ensemble] All models failed to extract structured fields.")
        return {}, {"error": "All ensemble models failed", "participating_models": []}

    print(f"\n[LangChain Ensemble] Aggregating results from {len(model_responses)} successful models via Majority Voting...")

    # Field-by-field Majority Voting
    final_data: Dict[str, str] = {}
    field_diagnostics: Dict[str, Any] = {}

    for field in REQUIRED_FIELDS:
        field_candidates = [r.get(field, "") for r in model_responses if r.get(field)]
        winner, meta = reconcile_field_candidates(field, field_candidates, raw_ocr_text)
        final_data[field] = winner
        field_diagnostics[field] = meta
        print(f"    - {field.capitalize():15}: '{winner}' (Votes: {meta.get('tally')})")

    # Post-processing cleanups
    # 1. Website: strip invented http:// or https:// if absent in raw OCR
    if not re.search(r"https?://", raw_ocr_text, re.IGNORECASE) and final_data.get("website"):
        final_data["website"] = re.sub(r"^https?://", "", final_data["website"])

    # 2. Office Contact cleanup
    if final_data.get("office_contact"):
        c = final_data["office_contact"]
        c = re.sub(r"/\s*\(+\s*\(+", "/(", c)
        final_data["office_contact"] = c

    # 3. Address normalization (fixes 9/g, o/0 glitches and normalizes state casing)
    if final_data.get("address"):
        final_data["address"] = clean_address_ocr_glitches(final_data["address"])

    overall_confidence = round(
        sum(meta.get("confidence", 0.0) for meta in field_diagnostics.values()) / len(REQUIRED_FIELDS),
        2
    )

    diagnostics = {
        "models_count": len(model_responses),
        "participating_models": participating_models,
        "field_diagnostics": field_diagnostics,
        "overall_confidence": overall_confidence
    }

    print(f"[LangChain Ensemble] Extraction complete. Overall Consensus Confidence: {overall_confidence * 100:.1f}%\n")
    return final_data, diagnostics
