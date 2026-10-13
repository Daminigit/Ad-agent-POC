# Architecture: AI-Powered Property Ad Generation Agent

## Overview

The system is a multi-stage AI pipeline built around a Streamlit chatbot. A real estate developer interacts through chat to submit documents, confirm facts, and receive ready-to-upload ad creatives for every major platform. The pipeline enforces strict data provenance — no ad is generated without a confirmed RERA number and a confirmed price list.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Developer (Browser)                          │
└───────────────────────────────┬─────────────────────────────────────┘
                                │  HTTP
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Streamlit Chatbot UI  (Python)                   │
│   Document upload · Fact confirmation · Output display · Download   │
└──────┬─────────────────────┬──────────────────────┬────────────────┘
       │                     │                      │
       ▼                     ▼                      ▼
┌─────────────┐   ┌──────────────────┐   ┌─────────────────────────┐
│  Document   │   │  Fact Extraction │   │    Ad Generation        │
│  Intake     │   │  & Confirmation  │   │    Orchestrator         │
│  Service    │   │  Service (LLM)   │   │                         │
└──────┬──────┘   └────────┬─────────┘   └────┬──────────┬─────────┘
       │                   │                   │          │
       ▼                   ▼                   ▼          ▼
┌─────────────┐   ┌──────────────────┐  ┌──────────┐ ┌──────────────┐
│  File Store │   │   Fact Sheet DB  │  │  Copy    │ │  Creative    │
│  (local /   │   │   (SQLite +      │  │  Writer  │ │  Generator   │
│   object    │   │    Pydantic)     │  │  (LLM)   │ │  Pipeline   │
│   store)    │   └──────────────────┘  └──────────┘ └──────┬───────┘
└─────────────┘                                              │
                                                    ┌────────┴────────┐
                                                    │                 │
                                              ┌─────▼─────┐   ┌──────▼──────┐
                                              │  Wan 2.2  │   │ Hyperframes │
                                              │  (fal.ai) │   │ (Node.js +  │
                                              │ img→video │   │  FFmpeg)    │
                                              └───────────┘   └─────────────┘
                                                    │                 │
                                                    └────────┬────────┘
                                                             │
                                                    ┌────────▼────────┐
                                                    │   Validation    │
                                                    │   Service       │
                                                    │  (OCR + rules)  │
                                                    └─────────────────┘
```

---

## Component Breakdown

### 1. Streamlit Chatbot UI

**Role:** The single entry point for the developer.

**Responsibilities:**
- Drive the document intake conversation (one file at a time)
- Display extracted facts for field-by-field confirmation
- Show output creatives grouped by platform
- Provide download links for all creatives
- Handle return visits and update flows

**Key interactions:**
- Calls the **Document Intake Service** when a file is uploaded
- Calls the **Fact Extraction Service** after each document is processed
- Calls the **Ad Generation Orchestrator** once all required facts are confirmed
- Displays results from the **Validation Service**

---

### 2. Document Intake Service

**Role:** Accept, validate, and store raw developer documents.

**Responsibilities:**
- Accept uploads: PDFs, images (renders, price list photos), certificates
- Detect and reject blurry or cut-off images (quality check)
- Track missing documents and re-prompt at the end of intake
- Store files to the file store with a manifest (filename, type, upload time, uploader)

**Required document types:**

| Document | Required? |
|---|---|
| RERA registration certificate | ✅ Mandatory (blocks generation) |
| Current price list (with date) | ✅ Mandatory (blocks generation) |
| Approved floor plans | Optional |
| Brochure (PDF) | Optional |
| Exterior renders (3–4) | Optional |
| Interior renders (2 per unit type) | Optional |
| Logo & brand colours | Optional |
| Marketing contact | Optional |

---

### 3. Fact Extraction & Confirmation Service

**Role:** Extract structured facts from raw documents using the LLM and get developer sign-off.

**Responsibilities:**
- Send each document (image/PDF) to the LLM for structured extraction
- Populate the Fact Sheet with extracted values
- Present each extracted field to the developer for confirmation
- Update the Fact Sheet with the confirmation record (who, when)
- Block downstream generation if mandatory facts are unconfirmed

**Extracted fields:**

```
project_name, rera_number, locality, unit_types[],
carpet_area_sqft, saleable_area_sqft, price_min_paise,
price_max_paise, possession_date, construction_stage,
amenities[], landmarks[], travel_times{}
```

**Provenance record (per field):**
```json
{
  "value": "14200000",
  "source_doc": "price_list_oct2026.jpg",
  "source_page": 1,
  "confirmed_by": "Rahul Mehta",
  "confirmed_at": "2026-09-21T14:30:00+05:30"
}
```

> **Security:** All text extracted from documents is treated as data only. Prompt injection from document content is explicitly prevented.

---

### 4. Fact Sheet Database

**Role:** Single source of truth for all confirmed project data.

**Technology:** SQLite + Pydantic models

**Schema (logical):**

```
Project
├── id, name, rera_number, locality, …
├── Units[]  (type, carpet_sqft, saleable_sqft, price_min, price_max)
├── Amenities[]
├── Landmarks[]  (name, distance_minutes)
├── ConfirmedFacts[]  (field, value, source_doc, source_page, confirmed_by, confirmed_at)
└── ChangeLog[]  (field, old_value, new_value, changed_by, changed_at)
```

---

### 5. Ad Copy Writer

**Role:** Generate platform-compliant ad copy from confirmed facts only.

**Technology:** Groq LLM (`llama-3.3-70b-versatile` or `mixtral-8x7b-32768`)

**Document pre-processing pipeline** (runs before LLM call):
- PDFs → images via `pdf2image` (poppler) → text via `pytesseract` OCR
- Images (renders, price list photos) → text via `pytesseract` OCR
- Extracted text is passed to Groq as plain context — Groq does **not** receive raw files

**Platform limits** (read from `config/platforms.yaml`):

| Platform | Asset | Limit |
|---|---|---|
| Google Search | Headline | 30 chars, up to 15 |
| Google Search | Description | 90 chars, up to 4 |
| Meta | Primary text hook | ~125 chars |
| Meta | Headline | 40 chars |
| Meta | Link description | 30 chars |

**Rules:**
- LLM prompt includes only the confirmed fact sheet — no raw document text
- Output is parsed and validated against character limits before saving
- Copy is regenerated if any field exceeds its limit

---

### 6. Creative Generation Pipeline

#### 6a. Image Preparation

- Render images are cropped to the target aspect ratio **before** any processing
- 9:16 crop is performed first (portrait) so the building is never cut off during animation
- `"Artist's impression"` watermark is baked in at this stage

#### 6b. Wan 2.2 — Image-to-Video (via `fal.ai`)

- Accepts the cropped render as input
- Applies gentle motion: slow zoom, parallax, drifting clouds
- **Never** uses text-to-image generation for buildings — only developer-supplied renders are animated
- Returns short video clips (≤30s)

#### 6c. Hyperframes — Reel & Image Assembly (Node.js 22+ + FFmpeg)

- One Hyperframes template per output shape (9:16, 4:5, 1:1, etc.)
- Combines: animated clip + price overlay + logo + RERA number + licensed music bed
- Renders final output files:

| Format | Variants |
|---|---|
| Reels | 15s · 30s × 9:16 · 4:5 |
| Images | Meta · LinkedIn · X · Reddit · Google Display (all sizes) |

---

### 7. Validation Service

**Role:** Gate-check every creative before it is presented to the developer.

**Checks:**

| Check | Method |
|---|---|
| Numbers match fact sheet | String normalisation + fact lookup (`"8 min"` ↔ `"8 minutes"`) |
| Character limits respected | Rule engine from `config/platforms.yaml` |
| RERA number visible | OCR (Tesseract) on every image and reel frame |
| `"Artist's impression"` present | OCR on every creative from a render |
| RERA + price list confirmed | Pre-generation gate check |

**Output per creative:** `{ status: "passed" | "failed", reasons: [] }`

---

### 8. Return Visit / Update Flow

When the developer returns for a repeat generation:

1. Load the existing Fact Sheet from the database
2. Prompt confirmation of the four critical facts:
   - Possession date
   - Price range
   - Available unit types
   - Construction stage
3. Write any changes to `ChangeLog` with `changed_by` and `changed_at`
4. Re-run Ad Copy Writer and Creative Generation Pipeline with updated facts

---

## Data Flow Summary

```
Developer uploads documents
        │
        ▼
Document Intake Service  ──►  File Store
        │
        ▼
Fact Extraction (LLM) ──►  Fact Sheet DB (unconfirmed)
        │
        ▼
Developer confirms facts  ──►  Fact Sheet DB (confirmed + provenance)
        │
        ▼
[Gate: RERA + price list confirmed?]
        │  YES
        ▼
Ad Copy Writer (LLM)  ──►  Platform copy drafts
        │
        ▼
Image Prep  ──►  Wan 2.2 (fal)  ──►  Animated clips
        │
        ▼
Hyperframes + FFmpeg  ──►  Reels + Images
        │
        ▼
Validation Service (OCR + rules)
        │
        ▼
Streamlit UI  ──►  Developer downloads creatives
```

---

## Configuration

All platform limits and creative specs live in a single file:

```
config/
└── platforms.yaml      # character limits, sizes, aspect ratios, durations
```

This ensures limits can be updated without touching application code.

---

## Tech Stack Summary

| Layer | Technology |
|---|---|
| UI & orchestration | Python 3.11+, Streamlit |
| LLM (extraction + copy) | Groq (`llama-3.3-70b-versatile`) |
| Data storage | SQLite + Pydantic |
| Image-to-video | Wan 2.2 via `fal.ai` |
| Video & image assembly | Hyperframes (Node.js 22+) + FFmpeg |
| OCR / validation | Tesseract |
| File storage | Local filesystem (or object store) |
| Config | `config/platforms.yaml` |

---

## Key Design Principles

1. **Confirmed facts only** — the LLM never sees raw document text when writing ad copy; it only sees the validated fact sheet.
2. **No generative buildings** — Wan is used purely to animate developer-supplied renders. Text-to-image for building exteriors is explicitly prohibited.
3. **Full provenance** — every fact carries its source document, page, confirming person and timestamp.
4. **Config-driven limits** — all platform character limits and creative specs are externalised to `config/platforms.yaml`.
5. **Gate before generation** — a RERA number and a confirmed price list are hard prerequisites; the pipeline will not proceed without them.
6. **Prompt injection defence** — document content is never interpolated directly into LLM prompts as instructions.
