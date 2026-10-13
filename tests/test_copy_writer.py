"""
Phase 5 test — Ad Copy Writer
Run with: python3 tests/test_copy_writer.py
"""

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.fact_sheet import Project, UnitType, Landmark
from models.db import save_project
from services.copy_writer import (
    build_fact_context,
    validate_copy_limits,
    generate_copy,
    get_copy,
    copy_to_display,
    _enforce_limits,
)


# ── Sample project ─────────────────────────────

def make_confirmed_project() -> Project:
    pid = str(uuid.uuid4())
    p = Project(
        id=pid,
        name="Aurelia Heights",
        rera_number="PRM/KA/RERA/1251/446",
        locality="Whitefield-Hoodi, Bengaluru",
        possession_date="Dec 2027",
        construction_stage="Under construction",
        units=[
            UnitType(type_name="2 BHK", carpet_sqft=1100, saleable_sqft=1380,
                     price_min=9800000, price_max=11000000),
            UnitType(type_name="3 BHK", carpet_sqft=1680, saleable_sqft=2100,
                     price_min=14200000, price_max=15800000),
        ],
        amenities=["Swimming pool", "Clubhouse", "Gym", "Children's play area",
                   "Landscaped gardens", "24x7 security"],
        landmarks=[
            Landmark(name="ITPL",       distance_minutes=8),
            Landmark(name="Hoodi Metro",distance_minutes=5),
        ],
    )
    # Confirm mandatory gate facts
    p.confirm_fact("rera_number", "PRM/KA/RERA/1251/446", "rera_cert.jpg", "Rahul")
    p.confirm_fact("price_range", "₹98L – ₹1.58 Cr", "price_list.jpg", "Rahul")
    save_project(p.model_dump(mode="json"))
    return p


# ── Tests ─────────────────────────────────────

def test_fact_context_built():
    p = make_confirmed_project()
    ctx = build_fact_context(p)
    assert "Aurelia Heights" in ctx
    assert "PRM/KA/RERA/1251/446" in ctx
    assert "3 BHK" in ctx
    assert "ITPL" in ctx
    assert "₹1.42 Cr" in ctx
    print("✓ Fact context built correctly")
    print(f"  Preview:\n{ctx[:300]}...")


def test_enforce_limits():
    raw = {
        "google_search": {
            "headlines": [
                "A" * 40,   # too long → must be trimmed to 30
                "Short",
            ] + ["H"] * 20,  # too many → must be capped at 15
            "descriptions": [
                "D" * 100,  # too long → must be trimmed to 90
            ] * 6,           # too many → must be capped at 4
        },
        "meta": {
            "primary_text": "Hook text here",
            "headline": "B" * 50,     # too long → trimmed to 40
            "link_description": "C" * 35,  # too long → trimmed to 30
        }
    }
    enforced = _enforce_limits(raw)
    gs = enforced["google_search"]
    meta = enforced["meta"]

    assert all(len(h) <= 30 for h in gs["headlines"]), "Headline too long"
    assert len(gs["headlines"]) <= 15, "Too many headlines"
    assert all(len(d) <= 90 for d in gs["descriptions"]), "Description too long"
    assert len(gs["descriptions"]) <= 4, "Too many descriptions"
    assert len(meta["headline"]) <= 40, "Meta headline too long"
    assert len(meta["link_description"]) <= 30, "Meta link too long"
    print(f"✓ Limits enforced: {len(gs['headlines'])} headlines, "
          f"{len(gs['descriptions'])} descriptions")


def test_validate_copy_limits_clean():
    clean = {
        "google_search": {
            "headlines": ["3 BHK from ₹1.42 Cr", "8 min to ITPL"],
            "descriptions": ["Aurelia Heights, Whitefield. Possession Dec 2027."],
        },
        "meta": {
            "primary_text": "3 BHK, 1,680 sq ft, ₹1.42 Cr. 8 min from ITPL.",
            "headline": "Aurelia Heights",
            "link_description": "Book a site visit",
        }
    }
    violations = validate_copy_limits(clean)
    assert violations == [], f"Clean copy has violations: {violations}"
    print("✓ Clean copy passes validation with zero violations")


def test_validate_copy_limits_violations():
    bad = {
        "google_search": {
            "headlines": ["This headline is definitely way too long for Google"],
            "descriptions": [],
        },
        "meta": {
            "primary_text": "ok",
            "headline": "This meta headline is far too long for the limit",
            "link_description": "This link description is way too long for Meta",
        }
    }
    violations = validate_copy_limits(bad)
    assert len(violations) >= 3, f"Expected ≥3 violations, got: {violations}"
    print(f"✓ Violations correctly detected: {len(violations)} found")


def test_gate_blocked_without_confirmation():
    p = Project(id=str(uuid.uuid4()), name="Test")
    try:
        generate_copy(p)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "gate" in str(e).lower()
    print("✓ Generation gate blocks unconfirmed project")


def test_generate_copy_live():
    p = make_confirmed_project()
    ad_copy = generate_copy(p)

    gs = ad_copy.google_search
    meta = ad_copy.meta

    assert len(gs.headlines) > 0,    "No headlines generated"
    assert len(gs.descriptions) > 0, "No descriptions generated"
    assert meta.primary_text,        "No Meta primary text"
    assert meta.headline,            "No Meta headline"
    assert meta.link_description,    "No Meta link description"

    # All within limits
    violations = validate_copy_limits(ad_copy.model_dump(mode="json"))
    assert violations == [], f"Generated copy violates limits: {violations}"

    print(f"✓ Copy generated — {len(gs.headlines)} headlines, "
          f"{len(gs.descriptions)} descriptions")
    print(f"\n  Google headlines:")
    for h in gs.headlines:
        print(f"    [{len(h):2d}] {h}")
    print(f"\n  Google descriptions:")
    for d in gs.descriptions:
        print(f"    [{len(d):2d}] {d}")
    print(f"\n  Meta primary text:\n    {meta.primary_text[:200]}")
    print(f"\n  Meta headline:         [{len(meta.headline):2d}] {meta.headline}")
    print(f"  Meta link description: [{len(meta.link_description):2d}] {meta.link_description}")

    return ad_copy, p.id


def test_copy_persisted_and_loaded(ad_copy, project_id):
    loaded = get_copy(project_id)
    assert loaded is not None, "Copy not found in DB"
    assert loaded.google_search.headlines == ad_copy.google_search.headlines
    print("✓ Copy persisted to DB and reloaded correctly")


def test_copy_to_display(ad_copy):
    display = copy_to_display(ad_copy)
    gs = display["google_search"]
    assert all("ok" in h for h in gs["headlines"])
    assert all(h["ok"] for h in gs["headlines"]), "Display shows limit violations"
    print(f"✓ copy_to_display: all {len(gs['headlines'])} headlines within limit")


# ── Runner ────────────────────────────────────

if __name__ == "__main__":
    print("\n=== Phase 5: Ad Copy Writer — tests ===\n")

    tests_offline = [
        test_enforce_limits,
        test_validate_copy_limits_clean,
        test_validate_copy_limits_violations,
        test_gate_blocked_without_confirmation,
        test_fact_context_built,
    ]
    tests_live = [
        test_generate_copy_live,
    ]

    passed = failed = 0

    print("--- Offline logic tests ---")
    for t in tests_offline:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"✗ {t.__name__}: {e}")
            import traceback; traceback.print_exc()
            failed += 1

    print("\n--- Live Groq API tests ---")
    try:
        ad_copy, pid = test_generate_copy_live()
        passed += 1
        for t in [
            lambda: test_copy_persisted_and_loaded(ad_copy, pid),
            lambda: test_copy_to_display(ad_copy),
        ]:
            try:
                t()
                passed += 1
            except Exception as e:
                print(f"✗ {e}")
                import traceback; traceback.print_exc()
                failed += 1
    except Exception as e:
        print(f"✗ test_generate_copy_live: {e}")
        import traceback; traceback.print_exc()
        failed += 1

    total = passed + failed
    print(f"\n{'='*50}")
    print(f"Passed: {passed}/{total}", "✓" if failed == 0 else "✗")
    if failed:
        sys.exit(1)
