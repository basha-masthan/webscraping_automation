# Codex / AI Live Handoff

This document describes the current extraction and verification system for a new AI agent working in this repository.

## Purpose

The project reads business-card images from Zen Data Protsk, extracts seven fields, fills the portal form, records completed work in SQLite, and independently verifies submitted forms against their original images.

The seven fields are always:

1. `name`
2. `designation`
3. `company`
4. `website`
5. `address`
6. `email`
7. `office_contact`

## Main entry points

| File | Responsibility |
| --- | --- |
| `data_entry_automation.py` | Browser workflow, OCR, extraction, portal fill, review pause, submit, and database save. |
| `langchain_extractor.py` | Parallel Groq/OpenRouter/local-brain extraction and field reconciliation. |
| `brain_engine.py` | Local learned domain/company graph, examples, spacing patterns, and offline prediction. |
| `verify_engine.py` | Re-reads source images and compares extraction against submitted portal data. |
| `db_manager.py` | SQLite schema and all record, failure, and verification access. |
| `web_dashboard.py`, `web/` | Local dashboard and verification user interface. |

## Current extraction order

1. Download the complete source image and capture the rendered browser image.
2. Run RapidOCR on raw, padded, Otsu, and 2× enlarged versions.
3. Choose an OCR pass using field evidence: valid email, phone number, ZIP, website, readable text, and a complete seven-segment `*` layout. Raw character count is not sufficient evidence.
4. Treat `*` as the primary boundary. Exactly six separators create seven left-to-right fields in the fixed order above.
5. Use the local brain and cloud ensemble to correct text only within the corresponding field boundary.
6. Run strict type checks before a value can enter a field.
7. Fill the portal inputs, confirm all seven DOM values, wait for human review, submit, and save the confirmed record.

## Non-negotiable star rule

If OCR returns exactly seven non-empty segments separated by `*`, do not move text between segments.

Example:

```text
Name * Designation * Company * Website * Address * Email * Office contact
```

The model may repair characters inside a segment, such as `cisc0.com` to `cisco.com`, but it must not use an email, phone, or address fragment to fill an adjacent field.

When the star layout is missing, has an empty segment, or has the wrong segment count, fall back to semantic parsing and mark uncertain cases for review.

## Validation rules

- Email must be a single valid email address with no spaces.
- Office contact must be a phone number or an explicit placeholder such as `No Data`.
- Website cannot be a phone number or email.
- Name, designation, and company cannot contain address, phone, URL, or email content.
- Addresses may span visual lines, but remain one star-delimited field when stars are available.
- Preserve every valid phone number in `office_contact`, separated by ` / `.

## OCR repairs already implemented

- 2× cubic enlargement improves thin bottom rows containing email and phone values.
- `0?Nel` is normalized to `O'Nel` only in address text.
- `g`/`o` digit mistakes are normalized in numeric address and ZIP contexts.
- OCR-equivalent email corrections keep the consensus spelling when the difference is a common glyph error, for example `cisc0.com` versus `cisco.com`.
- A designation acronym may remove an inserted lowercase OCR stroke, for example `CiISO` becomes `CISO`.

## Ensemble provider behavior

- Groq: `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, and `qwen/qwen3.8-27b`.
- OpenRouter: Llama 3.3 70B and Qwen 2.5 72B when credits are available.
- Outputs are capped at 700 tokens because seven short fields do not need large completions. This avoids excessive OpenRouter credit reservations and Groq output rate-limit requests.
- Provider failure must not erase deterministic OCR, star boundaries, or local-brain output.

## Failure and review protocol

1. If required data is missing, log it to `unfilled_records` before retrying model recovery.
2. Retry the same QR once after an extraction failure.
3. Confirm all seven values in browser DOM after filling.
4. Never silently submit a form with blank required inputs.
5. `verification_records` keeps the independent source-image comparison:
   - `resolved` means the record is approved or cleared.
   - `blocked` means it requires attention.

## Dashboard

The **Verify Submissions** screen includes **Modified by Codex / AI Live**. It explains the safeguards currently active in the extractor. It is a documentation panel; it does not change the existing Resolved or Blocked review state of submitted records.

## Recent verified examples

### 8x8 card

- Correct email: `ramana.sampangi@8x8.com`
- Correct address: `2125 O'Nel Dr. San Jose CA USA 95131`
- Correct office contact: `(408) 727-1885 / 866-879-8647`

### Cisco card, QR 500 observation

- OCR source email: `spitta@cisc0.com`
- Consensus correction: `spitta@cisco.com`
- The refiner now retains the consensus correction because it is equivalent after the known OCR `0`/`o` normalization and remains in the same email segment.

## Safe continuation guidance

- Read current code before changing extraction rules; this worktree contains user changes outside these safeguards.
- Do not replace star-first parsing with positional line splitting.
- Before running a large submission batch, inspect the first filled form and stop on any type mismatch, unexpected field movement, or uncorrected OCR corruption.
- Keep this file current after changes to extraction, validation, the local brain, provider configuration, or verification behavior.
