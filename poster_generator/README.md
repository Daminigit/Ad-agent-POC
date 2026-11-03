# 🎨 Festive Real-Estate Poster Generator

A standalone Python application that transforms a property's architectural renders, project details JSON, and brand logo into compliant, festive real-estate posters across standard social and print formats.

Backgrounds are generated using **Google Gemini Nano Banana** (`gemini-2.5-flash-image`) with strict architectural preservation prompts. **ALL typography, brand logo, and RERA disclosures are composited using Pillow—never by AI.**

---

## 📐 Supported Sizes (Version 1)

Version 1 produces exactly **TWO** posters per run:
1. **Instagram Post**: `1080 x 1350` (4:5 portrait feed)
2. **Story / WhatsApp**: `1080 x 1920` (9:16 vertical full-screen)

> **Note:** Additional formats (`Square 1080x1080`, `Facebook/LinkedIn 1200x628`, `Print A4 2480x3508`) are defined in `config.py` (`SIZES`) and can be toggled on without modifying other code.

---

## 🚀 Setup & Installation

```bash
# 1. Navigate to the poster_generator directory
cd poster_generator

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure your Google Gemini API key
cp .env.example .env
# Edit .env and set your GEMINI_API_KEY
```

---

## 🌐 Running the Web Application (Streamlit)

```bash
streamlit run app.py
```
Open your browser at `http://localhost:8501`.

### Web Workflow:
1. **Upload Assets**: Upload project JSON, brand logo PNG, and render images.
2. **Select Render & Festival**: Pick which approved render to feature and the festive theme.
3. **Headlines & Cost Preview**: Pick one of 3 AI headlines (or write custom), and click **"Preview cost"** ($0.06 total for 2 images).
4. **Generate Backgrounds**: Nano Banana synthesizes festive environments while preserving the building architecture.
5. **Approve Step**: Compare side-by-side with the original render. Verify the towers, facade, and windows before clicking **"Approve"**.
6. **Create Posters**: Pillow composites crisp typography, logo, and RERA strip. Download individual PNGs or a combined ZIP archive.

---

## 💻 Command Line Interface (CLI)

```bash
python poster.py \
  --project ../inputs/project.json \
  --logo ../inputs/logo.png \
  --render ../inputs/renders/tower_exterior.png \
  --festival Diwali \
  [--headline "This Diwali, Step Into Your Own Home"] \
  [--dry-run]
```

### CLI Features:
- Validates RERA number before any generation.
- Displays cost and background prompts.
- Interactively presents generated backgrounds for confirmation.
- Saves output files to `output/posters/{project}_{festival}_{format}.png`.
- Runs automated pre-save validation (RERA height >= 2.5%, font limits, WCAG AA contrast).

---

## 🛡️ RERA Compliance & Guardrails

- **Strict RERA Enforced**: Refuses to generate any poster if `rera.number` is missing or empty.
- **Dedicated High-Contrast Strip**: High-contrast white band across the bottom containing `RERA No: {rera.number}` (min 2.5% height) and standard legal disclaimers.
- **Draft Watermark**: Automatically burns a semi-transparent `DRAFT – NOT FOR PUBLICATION` diagonal watermark across unverified projects.
- **Never Hard-Coded**: Dynamically extracts promoter, units, location, pricing, and travel times from any project JSON.
