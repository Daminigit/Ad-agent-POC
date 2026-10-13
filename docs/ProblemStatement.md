# Problem Statement: AI-Powered Property Ad Generation Agent (Real Estate Use Case)

You are tasked with building an AI-powered agent that creates property advertisements for real estate developers. The system should collect project documents from the developer, turn them into confirmed facts, and generate platform-ready ad copy, images and reels by combining a Large Language Model (LLM), an image-to-video model and an HTML-to-video renderer.

> **Ads must be specific, not generic.**
> `"3 BHK, 1,680 sq ft, ₹1.42 Cr onwards. 8 minutes from ITPL. Possession Dec 2027."` attracts real buyers; `"Luxury living redefined"` attracts clicks from people who cannot afford the flat.

---

## Objective

Design and implement an application that:

- Collects project documents from the developer through a chatbot
- Extracts key project facts and gets the developer to confirm them
- Uses an LLM to write ad copy that fits each platform's limits
- Uses **Wan** (image-to-video) to add motion to the developer's own renders
- Uses **Hyperframes** to assemble reels and images with price, logo and RERA number
- Checks every ad for correct numbers and a visible RERA number
- Outputs ready-to-upload creatives in every platform size

---

## System Workflow

### 1. Document Intake (Chatbot)

Ask for one document at a time:

| Document | Notes |
|---|---|
| RERA registration certificate | Required before any generation |
| Current price list | Must include issue date |
| Approved floor plans | — |
| Brochure (PDF) | — |
| Exterior renders (3–4) | — |
| Interior renders (2 per unit type) | — |
| Logo and brand colours | — |
| Marketing contact (name and phone) | — |

- If a file is **blurry or cut off**, ask for it again
- If a document is **not available yet**, mark it missing and ask again at the end

> **Sample input:** a fictional project set (*"Aurelia Heights"*, Whitefield–Hoodi, Bengaluru) plus at least one real, messy document such as a phone photo of a price list.

---

### 2. Fact Extraction and Confirmation

Extract fields such as:

- Project name & RERA number
- Locality
- Unit types
- Carpet and saleable area
- Price range
- Possession date
- Construction stage
- Amenities
- Landmarks and travel times

**Confirmation flow:** Show extracted facts back and confirm field by field, e.g.:
> *"3 BHK, 1,680 sq ft, ₹1.42 Cr – ₹1.58 Cr — is that right?"*

**Rules:**
- Store prices as whole rupees (`₹1.42 Cr → 14200000`)
- Keep the source document, page, confirming person and time for every field
- Treat text inside documents as data, **never** as instructions

---

### 3. Ad Copy Generation

Use the LLM with **only confirmed facts** to write:

| Platform | Copy Specs |
|---|---|
| **Google Search** | Up to 15 headlines (30 chars each), 4 descriptions (90 chars each) |
| **Meta** | Primary text with hook in first ~125 chars, headline (40 chars), link description (30 chars) |

> All character limits are read from a single config file: `config/platforms.yaml`

---

### 4. Creative Generation

- Use **Wan 2.2** image-to-video (via `fal`) to add gentle motion to developer renders — slow zoom, drifting clouds. **Never generate a building from text.**
- Crop renders to vertical **before** animating, so the building is not cut off in 9:16
- Use **Hyperframes** templates (one per shape) to combine clips, price, logo, RERA number and a licensed music bed

**Output formats:**

| Type | Sizes |
|---|---|
| **Reels** | 15s and 30s, in 9:16 and 4:5 |
| **Images** | All platform sizes (Meta, LinkedIn, X, Reddit, Google Display) |

---

### 5. Validation

Every ad must pass the following checks:

- ✅ Every number matches the fact sheet (`"8 min"` = `"8 minutes"`, `"₹1.42 Cr"` = `"1.42 crore"`)
- ✅ Every text field is within its platform character limit
- ✅ RERA number is visible on every image and reel *(checked with OCR)*
- ✅ `"Artist's impression"` appears on anything made from a render
- 🚫 No generation without a confirmed RERA number and price list

---

### 6. Updates (Return Visit)

Before generating again, ask the developer to confirm the four facts ads depend on:

1. Possession date
2. Price range
3. Available unit types
4. Construction stage

Record any change with **who changed it and when**.

---

### 7. Output Display

Present results per platform in a user-friendly format:

- Ad copy
- Images in each size
- Reels in each length and shape
- Check status *(passed / failed, with reason)*

Allow **download** for manual upload to ad platforms.

---

## Tech Stack

| Component | Technology |
|---|---|
| Language & UI | Python 3.11+, Streamlit (chatbot UI) |
| Data storage | SQLite + Pydantic (fact sheet) |
| LLM | Any model capable of reading images and PDFs |
| Image-to-video | Wan 2.2 via `fal` |
| Video assembly | Hyperframes (Node.js 22+) + FFmpeg |
| RERA validation | OCR (e.g. Tesseract) |
