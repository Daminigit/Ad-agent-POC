"""
Phase 4 test — Fact Extraction & Confirmation Service
Run with: python3 tests/test_extraction.py
"""

import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.fact_sheet import Project
from models.db import save_project, load_project
from services.extraction import (
    extract_facts_from_text,
    merge_extracted_facts,
    confirm_fact,
    reject_fact,
    build_confirmation_prompts,
    get_unconfirmed_fields,
    process_document,
    _empty_facts,
)

# ── Sample OCR-style text mimicking a real price list photo ──

SAMPLE_PRICE_LIST_TEXT = """
AURELIA HEIGHTS — WHITEFIELD, BENGALURU

RERA Registration No.: PRM/KA/RERA/1251/446

Developer: Prestige Group

Unit Type    Carpet Area    Saleable Area    Price
2 BHK        1,100 sqft     1,380 sqft       ₹98 Lakhs – ₹1.10 Cr
3 BHK        1,680 sqft     2,100 sqft       ₹1.42 Cr – ₹1.58 Cr
3 BHK+Study  1,820 sqft     2,280 sqft       ₹1.65 Cr – ₹1.80 Cr

Possession: December 2027
Stage: Under Construction

Amenities: Swimming pool, Clubhouse, Gym, Children's play area,
           Landscaped gardens, 24x7 security

Nearby:
 - ITPL: 8 minutes
 - Hoodi Metro: 5 minutes
 - Manyata Tech Park: 25 minutes

Contact: Priya Sharma | +91-98765-43210
Issue date: October 2026
"""

SAMPLE_RERA_TEXT = """
KARNATAKA REAL ESTATE REGULATORY AUTHORITY
REGISTRATION CERTIFICATE

Project: Aurelia Heights
RERA Number: PRM/KA/RERA/1251/446
Developer: Prestige Group
Location: Whitefield-Hoodi, Bengaluru
Total Units: 240
Total Floors: 22
Total Towers: 3
Valid Till: December 2027
"""


def test_extract_facts_from_text():
    facts = extract_facts_from_text(SAMPLE_PRICE_LIST_TEXT, "price_list")
    assert facts.get("project_name"), f"project_name missing: {facts}"
    assert facts.get("rera_number"), f"rera_number missing: {facts}"
    assert facts.get("possession_date"), f"possession_date missing: {facts}"
    assert isinstance(facts.get("unit_types"), list) and len(facts["unit_types"]) > 0, \
        f"unit_types missing or empty: {facts}"
    assert isinstance(facts.get("amenities"), list) and len(facts["amenities"]) > 0, \
        f"amenities missing: {facts}"
    assert isinstance(facts.get("landmarks"), list) and len(facts["landmarks"]) > 0, \
        f"landmarks missing: {facts}"
    print(f"✓ Extraction: project='{facts['project_name']}', "
          f"rera='{facts['rera_number']}', "
          f"units={len(facts['unit_types'])}, "
          f"amenities={len(facts['amenities'])}, "
          f"landmarks={len(facts['landmarks'])}")
    return facts


def test_price_stored_as_rupees(facts):
    for unit in facts.get("unit_types", []):
        if unit.get("price_min"):
            assert unit["price_min"] > 100_000, \
                f"Price {unit['price_min']} looks like Cr, not rupees"
    print(f"✓ Prices stored as whole rupees: "
          f"{facts['unit_types'][0]['price_min']:,} – {facts['unit_types'][0]['price_max']:,}")


def test_merge_facts():
    project = Project(id=str(uuid.uuid4()), name=None)
    facts = {
        **_empty_facts(),
        "project_name": "Aurelia Heights",
        "rera_number":  "PRM/KA/RERA/1251/446",
        "locality":     "Whitefield",
        "unit_types": [{
            "type_name":     "3 BHK",
            "carpet_sqft":   1680,
            "saleable_sqft": 2100,
            "price_min":     14200000,
            "price_max":     15800000,
        }],
        "amenities": ["Swimming pool", "Gym"],
        "landmarks": [{"name": "ITPL", "distance_minutes": 8}],
    }
    project = merge_extracted_facts(project, facts, "price_list.jpg")

    assert project.name == "Aurelia Heights"
    assert project.rera_number == "PRM/KA/RERA/1251/446"
    assert len(project.units) == 1
    assert project.units[0].type_name == "3 BHK"
    assert len(project.amenities) == 2
    assert len(project.landmarks) == 1
    assert project.landmarks[0].distance_minutes == 8
    print(f"✓ Merge: name='{project.name}', units={len(project.units)}, "
          f"amenities={len(project.amenities)}, landmarks={len(project.landmarks)}")
    return project


def test_no_overwrite_existing(project):
    # Merging again should not duplicate amenities
    facts_again = {
        **_empty_facts(),
        "project_name": "Different Name",   # should NOT overwrite
        "amenities": ["Swimming pool"],     # duplicate — should NOT be added again
    }
    project = merge_extracted_facts(project, facts_again, "brochure.pdf")
    assert project.name == "Aurelia Heights"    # original preserved
    assert project.amenities.count("Swimming pool") == 1  # no duplicate
    print("✓ Merge does not overwrite existing fields or duplicate list items")


def test_confirm_fact():
    project_id = str(uuid.uuid4())
    p = Project(id=project_id, name="Aurelia Heights", rera_number="PRM/KA/RERA/1251/446")
    save_project(p.model_dump(mode="json"))

    updated = confirm_fact(
        project_id=project_id,
        field="rera_number",
        value="PRM/KA/RERA/1251/446",
        source_doc="rera_certificate.jpg",
        confirmed_by="Rahul Mehta",
    )
    assert updated.rera_confirmed is True
    assert "rera_number" in updated.confirmed_facts
    prov = updated.confirmed_facts["rera_number"]
    assert prov.confirmed_by == "Rahul Mehta"
    assert prov.value == "PRM/KA/RERA/1251/446"
    print(f"✓ Confirm RERA: gate={updated.rera_confirmed}, "
          f"confirmed_by='{prov.confirmed_by}'")
    return project_id


def test_reject_and_correct(project_id):
    updated = reject_fact(
        project_id=project_id,
        field="rera_number",
        correct_value="PRM/KA/RERA/1251/999",
        source_doc="rera_certificate.jpg",
        confirmed_by="Rahul Mehta",
    )
    assert updated.confirmed_facts["rera_number"].value == "PRM/KA/RERA/1251/999"
    print(f"✓ Reject & correct: new value='{updated.confirmed_facts['rera_number'].value}'")


def test_generation_gate(project_id):
    updated = confirm_fact(
        project_id=project_id,
        field="price_range",
        value="1.42 Cr - 1.58 Cr",
        source_doc="price_list.jpg",
        confirmed_by="Rahul Mehta",
    )
    assert updated.is_ready_for_generation(), "Generation gate should be open"
    print(f"✓ Generation gate: ready={updated.is_ready_for_generation()}")


def test_build_confirmation_prompts():
    facts = {
        **_empty_facts(),
        "project_name":   "Aurelia Heights",
        "rera_number":    "PRM/KA/RERA/1251/446",
        "possession_date": "Dec 2027",
        "unit_types": [{
            "type_name":   "3 BHK",
            "carpet_sqft": 1680,
            "saleable_sqft": 2100,
            "price_min":   14200000,
            "price_max":   15800000,
        }],
        "amenities": ["Pool", "Gym"],
        "landmarks": [{"name": "ITPL", "distance_minutes": 8}],
    }
    project = Project(id="test")
    prompts = build_confirmation_prompts(facts, project)
    assert len(prompts) >= 4
    fields = [p["field"] for p in prompts]
    assert "rera_number" in fields
    assert "unit_types" in fields
    assert "amenities" in fields
    assert "landmarks" in fields
    print(f"✓ Confirmation prompts: {len(prompts)} cards")
    for p in prompts:
        print(f"   {p['display_text'][:80]}")


def test_get_unconfirmed_fields():
    p = Project(
        id="x",
        name="Aurelia Heights",
        rera_number="PRM/KA/RERA/1251/446",
        locality="Whitefield",
    )
    unconfirmed = get_unconfirmed_fields(p)
    assert "project_name" in unconfirmed
    assert "rera_number" in unconfirmed
    print(f"✓ Unconfirmed fields: {unconfirmed}")


def test_empty_text_returns_empty_facts():
    facts = extract_facts_from_text("", "price_list")
    assert all(
        v is None or v == [] for v in facts.values()
    ), f"Expected empty facts for empty text: {facts}"
    print("✓ Empty document text → empty facts (no hallucination)")


# ── Runner ────────────────────────────────────

if __name__ == "__main__":
    print("\n=== Phase 4: Fact Extraction & Confirmation — tests ===\n")

    # --- Offline (no API) tests first ---
    print("--- Offline logic tests ---")
    offline = [
        lambda: test_no_overwrite_existing(test_merge_facts()),
        test_build_confirmation_prompts,
        test_get_unconfirmed_fields,
    ]

    # --- Live Groq API tests ---
    print("\n--- Live Groq API tests (require GROQ_API_KEY) ---")
    live_tests = [
        ("extract from price list text",  lambda: test_extract_facts_from_text()),
        ("prices stored as rupees",       lambda: test_price_stored_as_rupees(extract_facts_from_text(SAMPLE_PRICE_LIST_TEXT, "price_list"))),
        ("confirm fact + gate",           lambda: test_generation_gate(test_confirm_fact())),
        ("reject and correct fact",       lambda: test_reject_and_correct(test_confirm_fact())),
        ("empty text → empty facts",      test_empty_text_returns_empty_facts),
    ]

    passed = failed = 0

    for fn in offline:
        try:
            fn()
            passed += 1
        except Exception as e:
            print(f"✗ {e}")
            import traceback; traceback.print_exc()
            failed += 1

    for name, fn in live_tests:
        try:
            fn()
            passed += 1
        except Exception as e:
            print(f"✗ {name}: {e}")
            import traceback; traceback.print_exc()
            failed += 1

    total = passed + failed
    print(f"\n{'='*50}")
    print(f"Passed: {passed}/{total}", "✓" if failed == 0 else "✗")
    if failed:
        sys.exit(1)
