"""
Pydantic models for the Ad Generation Agent fact sheet.
These are the canonical data structures used across all services.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field
import uuid


# ─────────────────────────────────────────────
# Provenance & Change Tracking
# ─────────────────────────────────────────────

class ProvenanceRecord(BaseModel):
    """Full audit trail for a single confirmed fact."""
    value: str
    source_doc: str          # filename of the originating document
    source_page: int = 1     # page number within the document
    confirmed_by: str        # name of the developer who confirmed
    confirmed_at: datetime   # UTC timestamp of confirmation


class ChangeLogEntry(BaseModel):
    """Records a fact that was changed on a return visit."""
    field: str
    old_value: str
    new_value: str
    changed_by: str
    changed_at: datetime


# ─────────────────────────────────────────────
# Sub-entities
# ─────────────────────────────────────────────

class UnitType(BaseModel):
    """A single unit configuration (e.g. '3 BHK')."""
    type_name: str               # e.g. "3 BHK", "2 BHK + Study"
    carpet_sqft: float
    saleable_sqft: float
    price_min: int               # whole rupees, e.g. 14200000
    price_max: int


class Landmark(BaseModel):
    """A nearby point of interest with travel time."""
    name: str                    # e.g. "ITPL"
    distance_minutes: int        # driving/transit minutes


class Document(BaseModel):
    """A developer-uploaded raw document."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    doc_type: str                # e.g. "rera_certificate", "price_list"
    filename: str
    filepath: str
    uploaded_at: datetime
    status: str = "ok"           # "ok" | "blurry" | "missing"
    extracted_text: Optional[str] = None   # OCR / PDF text extracted


# ─────────────────────────────────────────────
# Core Project / Fact Sheet
# ─────────────────────────────────────────────

class Project(BaseModel):
    """
    The central fact sheet for a real estate project.
    All fields that feed into ad generation must pass through
    confirmed_facts before the generation gate is unlocked.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: Optional[str] = None
    rera_number: Optional[str] = None
    locality: Optional[str] = None
    possession_date: Optional[str] = None       # e.g. "Dec 2027"
    construction_stage: Optional[str] = None    # e.g. "Under construction"

    units: list[UnitType] = []
    amenities: list[str] = []
    landmarks: list[Landmark] = []
    documents: list[Document] = []

    # Provenance-backed confirmed facts
    # key = field name, value = ProvenanceRecord
    confirmed_facts: dict[str, ProvenanceRecord] = {}

    # Return-visit audit log
    change_log: list[ChangeLogEntry] = []

    # Generation gate flags — both must be True before ads can be generated
    rera_confirmed: bool = False
    price_list_confirmed: bool = False

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # ── Helpers ──────────────────────────────

    def is_ready_for_generation(self) -> bool:
        """Return True only if all hard prerequisites are confirmed."""
        has_rera = self.rera_confirmed or "rera_number" in self.confirmed_facts
        has_price = self.price_list_confirmed or "price_range" in self.confirmed_facts or "unit_types" in self.confirmed_facts
        return has_rera and has_price

    def confirm_fact(
        self,
        field: str,
        value: str,
        source_doc: str,
        confirmed_by: str,
        source_page: int = 1,
    ) -> None:
        """
        Record a developer-confirmed fact with full provenance.
        Automatically sets gate flags for RERA and price list.
        """
        self.confirmed_facts[field] = ProvenanceRecord(
            value=value,
            source_doc=source_doc,
            source_page=source_page,
            confirmed_by=confirmed_by,
            confirmed_at=datetime.now(timezone.utc),
        )
        if field == "rera_number":
            self.rera_number = value
            self.rera_confirmed = True
        if field in ("price_range", "unit_types"):
            self.price_list_confirmed = True
        self.updated_at = datetime.now(timezone.utc)

    def update_fact(
        self,
        field: str,
        new_value: str,
        changed_by: str,
    ) -> None:
        """
        Update a previously confirmed fact (return visit).
        Records the change in the audit log.
        """
        old_value = (
            self.confirmed_facts[field].value
            if field in self.confirmed_facts
            else ""
        )
        self.change_log.append(
            ChangeLogEntry(
                field=field,
                old_value=old_value,
                new_value=new_value,
                changed_by=changed_by,
                changed_at=datetime.now(timezone.utc),
            )
        )
        # Re-confirm with updated value, preserving other provenance fields
        if field in self.confirmed_facts:
            self.confirmed_facts[field] = ProvenanceRecord(
                value=new_value,
                source_doc=self.confirmed_facts[field].source_doc,
                source_page=self.confirmed_facts[field].source_page,
                confirmed_by=changed_by,
                confirmed_at=datetime.now(timezone.utc),
            )
        self.updated_at = datetime.now(timezone.utc)


# ─────────────────────────────────────────────
# Ad Copy
# ─────────────────────────────────────────────

class GoogleSearchCopy(BaseModel):
    headlines: list[str]      # each ≤ 30 chars, up to 15
    descriptions: list[str]   # each ≤ 90 chars, up to 4


class MetaCopy(BaseModel):
    primary_text: str         # hook in first ~125 chars
    headline: str             # ≤ 40 chars
    link_description: str     # ≤ 30 chars


class AdCopy(BaseModel):
    """Generated ad copy for all platforms."""
    project_id: str
    google_search: GoogleSearchCopy
    meta: MetaCopy
    voice_script: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ─────────────────────────────────────────────
# Validation Results
# ─────────────────────────────────────────────

class ValidationResult(BaseModel):
    """Result of validating a single creative."""
    creative_path: str
    status: str                # "passed" | "failed"
    reasons: list[str] = []
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
