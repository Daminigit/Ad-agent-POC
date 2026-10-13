"""
Fact Extraction & Confirmation Service
=======================================
Responsibilities:
  1. Send OCR-extracted document text to Groq and get structured JSON facts
  2. Merge new facts into the project's unconfirmed staging area
  3. Present facts for developer confirmation (field by field)
  4. Write confirmed facts + provenance into the Project model
  5. Enforce the generation gate (RERA + price list must both be confirmed)
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import groq as groq_sdk
from dotenv import load_dotenv

from models.fact_sheet import Project, UnitType, Landmark, ProvenanceRecord
from models.db import save_project, load_project

load_dotenv()

# ─────────────────────────────────────────────
# Groq client
# ─────────────────────────────────────────────

_client = groq_sdk.Groq(api_key=os.getenv("GROQ_API_KEY"))
_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

EXTRACTION_PROMPT = Path("prompts/extraction.txt").read_text()

# ─────────────────────────────────────────────
# Human-readable field labels for the UI
# ─────────────────────────────────────────────

FIELD_LABELS: dict[str, str] = {
    "project_name":            "Project name",
    "rera_number":             "RERA number",
    "locality":                "Locality / area",
    "city":                    "City",
    "possession_date":         "Possession date",
    "construction_stage":      "Construction stage",
    "unit_types":              "Unit types & pricing",
    "amenities":               "Amenities",
    "landmarks":               "Nearby landmarks",
    "developer_name":          "Developer name",
    "marketing_contact_name":  "Marketing contact name",
    "marketing_contact_phone": "Marketing contact phone",
    "total_units":             "Total units",
    "total_floors":            "Total floors",
    "total_towers":            "Total towers",
    "price_range":             "Price range",
}


# ─────────────────────────────────────────────
# LLM Extraction
# ─────────────────────────────────────────────

def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences that the LLM sometimes adds."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop first line (```json or ```) and last line (```)
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return text.strip()


def extract_facts_from_text(
    document_text: str,
    doc_type: str = "unknown",
) -> dict[str, Any]:
    """
    Send OCR-extracted document text to Groq and return a structured facts dict.

    Args:
        document_text: Plain text extracted from the document via OCR / pdf2image.
        doc_type:      Document category (e.g. 'rera_certificate', 'price_list').

    Returns:
        Parsed JSON dict matching the extraction schema.
        Fields that could not be extracted are None.

    Raises:
        ValueError: If the LLM returns malformed JSON after retries.
    """
    if not document_text or not document_text.strip():
        return _empty_facts()

    # Merge system prompt + document into a single user message
    # (openai/gpt-oss-* on Groq suppresses output with system role)
    combined_message = (
        f"{EXTRACTION_PROMPT}\n\n"
        f"---\n\n"
        f"Document type: {doc_type}\n\n"
        f"--- DOCUMENT TEXT START ---\n"
        f"{document_text[:12000]}\n"
        f"--- DOCUMENT TEXT END ---"
    )

    for attempt in range(3):
        response = _client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "user", "content": combined_message},
            ],
            temperature=0.0,
            max_tokens=4096,
        )
        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise ValueError("Groq truncated extraction response (finish_reason=length).")

        raw = choice.message.content or ""
        raw = _strip_code_fences(raw)
        if not raw:
            if attempt < 2:
                continue
            return _empty_facts()

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Try extracting JSON from within the response
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            if attempt == 2:
                raise ValueError(
                    f"Groq returned malformed JSON after 3 attempts.\nRaw: {raw[:500]}"
                )

    return _empty_facts()


def _empty_facts() -> dict[str, Any]:
    """Return a skeleton facts dict with all fields set to None."""
    return {
        "project_name":            None,
        "rera_number":             None,
        "locality":                None,
        "city":                    None,
        "possession_date":         None,
        "construction_stage":      None,
        "unit_types":              [],
        "amenities":               [],
        "landmarks":               [],
        "developer_name":          None,
        "marketing_contact_name":  None,
        "marketing_contact_phone": None,
        "total_units":             None,
        "total_floors":            None,
        "total_towers":            None,
    }


# ─────────────────────────────────────────────
# Fact Merging (staging area before confirmation)
# ─────────────────────────────────────────────

def merge_extracted_facts(
    project: Project,
    new_facts: dict[str, Any],
    source_doc: str,
) -> Project:
    """
    Merge newly extracted facts into the project.
    Only fills fields that are currently empty — does not overwrite confirmed facts.
    Sub-entities (units, amenities, landmarks) are extended, not replaced.

    Args:
        project:   Current Project object.
        new_facts: Dict returned by extract_facts_from_text().
        source_doc: Filename of the source document.

    Returns:
        Updated Project (not yet saved to DB).
    """
    # Scalar fields — only set if currently None
    scalar_map = {
        "project_name":       "name",
        "rera_number":        "rera_number",
        "locality":           "locality",
        "possession_date":    "possession_date",
        "construction_stage": "construction_stage",
    }
    for fact_key, model_attr in scalar_map.items():
        val = new_facts.get(fact_key)
        if val and not getattr(project, model_attr):
            setattr(project, model_attr, str(val))

    # Unit types — append new ones (avoid duplicates by type_name)
    existing_names = {u.type_name for u in project.units}
    for u in new_facts.get("unit_types") or []:
        if u.get("type_name") and u["type_name"] not in existing_names:
            try:
                project.units.append(UnitType(
                    type_name=u["type_name"],
                    carpet_sqft=float(u["carpet_sqft"] or 0),
                    saleable_sqft=float(u["saleable_sqft"] or 0),
                    price_min=int(u["price_min"] or 0),
                    price_max=int(u["price_max"] or 0),
                ))
                existing_names.add(u["type_name"])
            except (TypeError, ValueError):
                pass   # skip malformed unit entries

    # Amenities — extend (deduplicate)
    existing_amenities = set(project.amenities)
    for a in new_facts.get("amenities") or []:
        if a and a not in existing_amenities:
            project.amenities.append(a)
            existing_amenities.add(a)

    # Landmarks — extend (deduplicate by name)
    existing_landmarks = {lm.name for lm in project.landmarks}
    for lm in new_facts.get("landmarks") or []:
        if lm.get("name") and lm["name"] not in existing_landmarks:
            try:
                project.landmarks.append(Landmark(
                    name=lm["name"],
                    distance_minutes=int(lm.get("distance_minutes") or 0),
                ))
                existing_landmarks.add(lm["name"])
            except (TypeError, ValueError):
                pass

    project.updated_at = datetime.now(timezone.utc)
    return project


# ─────────────────────────────────────────────
# Full document → project pipeline
# ─────────────────────────────────────────────

def process_document(
    project_id: str,
    doc_type: str,
    document_text: str,
    source_doc: str,
) -> tuple[Project, dict[str, Any]]:
    """
    Extract facts from document text, merge into project, and save to DB.

    Returns:
        (updated_project, raw_facts_dict)
    """
    # Load or create project
    raw = load_project(project_id)
    project = Project(**raw) if raw else Project(id=project_id)

    # Extract
    facts = extract_facts_from_text(document_text, doc_type)

    # Merge (unconfirmed staging)
    project = merge_extracted_facts(project, facts, source_doc)

    # Save
    save_project(project.model_dump(mode="json"))

    return project, facts


# ─────────────────────────────────────────────
# Confirmation
# ─────────────────────────────────────────────

def confirm_fact(
    project_id: str,
    field: str,
    value: str,
    source_doc: str,
    confirmed_by: str,
    source_page: int = 1,
) -> Project:
    """
    Developer confirms a specific fact field.
    Saves the ProvenanceRecord and updates gate flags.

    Args:
        project_id:   Project UUID.
        field:        Field name (e.g. 'rera_number', 'price_range').
        value:        Confirmed value as a string.
        source_doc:   Filename of the document the fact came from.
        confirmed_by: Name of the developer who confirmed.
        source_page:  Page number in the source document.

    Returns:
        Updated Project.
    """
    raw = load_project(project_id)
    if not raw:
        raise ValueError(f"Project {project_id} not found in database.")

    project = Project(**raw)
    project.confirm_fact(
        field=field,
        value=value,
        source_doc=source_doc,
        confirmed_by=confirmed_by,
        source_page=source_page,
    )
    save_project(project.model_dump(mode="json"))
    return project


def reject_fact(
    project_id: str,
    field: str,
    correct_value: str,
    source_doc: str,
    confirmed_by: str,
) -> Project:
    """
    Developer rejects an extracted fact and provides the correct value.
    Confirms the corrected value immediately with provenance.
    """
    return confirm_fact(
        project_id=project_id,
        field=field,
        value=correct_value,
        source_doc=source_doc,
        confirmed_by=confirmed_by,
    )


# ─────────────────────────────────────────────
# Confirmation UI Helpers
# ─────────────────────────────────────────────

def build_confirmation_prompts(
    facts: dict[str, Any],
    project: Project,
) -> list[dict]:
    """
    Build a list of confirmation cards to show the developer in the UI.
    Each card has: field, label, extracted_value, display_text.

    Only includes fields that have a non-null extracted value.
    Unit types, amenities, and landmarks are grouped into single cards.
    """
    prompts: list[dict] = []

    # Scalar fields
    scalar_fields = [
        "project_name", "rera_number", "locality", "city",
        "possession_date", "construction_stage",
        "developer_name", "marketing_contact_name", "marketing_contact_phone",
        "total_units", "total_floors", "total_towers",
    ]
    for field in scalar_fields:
        val = facts.get(field)
        if val is not None:
            prompts.append({
                "field":           field,
                "label":           FIELD_LABELS.get(field, field),
                "extracted_value": str(val),
                "display_text":    f"**{FIELD_LABELS.get(field, field)}**: {val}",
                "type":            "scalar",
            })

    # Unit types
    units = facts.get("unit_types") or []
    if units:
        lines = []
        for u in units:
            price_str = ""
            if u.get("price_min") and u.get("price_max"):
                lo = u["price_min"] / 1e7
                hi = u["price_max"] / 1e7
                price_str = f"₹{lo:.2f} Cr – ₹{hi:.2f} Cr"
            elif u.get("price_min"):
                price_str = f"₹{u['price_min'] / 1e7:.2f} Cr onwards"
            area_str = ""
            if u.get("carpet_sqft"):
                area_str = f"{u['carpet_sqft']} sqft carpet"
            parts = [p for p in [u.get("type_name"), area_str, price_str] if p]
            lines.append("  • " + ", ".join(parts))
        prompts.append({
            "field":           "unit_types",
            "label":           "Unit types & pricing",
            "extracted_value": json.dumps(units),
            "display_text":    "**Unit types & pricing**:\n" + "\n".join(lines),
            "type":            "complex",
        })

    # Amenities
    amenities = facts.get("amenities") or []
    if amenities:
        prompts.append({
            "field":           "amenities",
            "label":           "Amenities",
            "extracted_value": json.dumps(amenities),
            "display_text":    "**Amenities**: " + ", ".join(amenities),
            "type":            "complex",
        })

    # Landmarks
    landmarks = facts.get("landmarks") or []
    if landmarks:
        lines = [
            f"  • {lm['name']} — {lm.get('distance_minutes', '?')} min"
            for lm in landmarks
        ]
        prompts.append({
            "field":           "landmarks",
            "label":           "Nearby landmarks",
            "extracted_value": json.dumps(landmarks),
            "display_text":    "**Nearby landmarks**:\n" + "\n".join(lines),
            "type":            "complex",
        })

    return prompts


def get_unconfirmed_fields(project: Project) -> list[str]:
    """
    Return field names that have been extracted (project has a value)
    but have not yet been confirmed by the developer.
    """
    confirmed = set(project.confirmed_facts.keys())
    extracted: list[str] = []

    if project.name and "project_name" not in confirmed:
        extracted.append("project_name")
    if project.rera_number and "rera_number" not in confirmed:
        extracted.append("rera_number")
    if project.locality and "locality" not in confirmed:
        extracted.append("locality")
    if project.possession_date and "possession_date" not in confirmed:
        extracted.append("possession_date")
    if project.construction_stage and "construction_stage" not in confirmed:
        extracted.append("construction_stage")
    if project.units and "unit_types" not in confirmed:
        extracted.append("unit_types")
    if project.amenities and "amenities" not in confirmed:
        extracted.append("amenities")
    if project.landmarks and "landmarks" not in confirmed:
        extracted.append("landmarks")

    return extracted
