# Ad Generation Agent — POC

AI-powered property ad generation agent for real estate developers.  
See [`docs/ProblemStatement.md`](docs/ProblemStatement.md) for the full brief  
and [`docs/architecture.md`](docs/architecture.md) for the system design.

---

## Quick Start

### 1. Clone & enter the repo
```bash
git clone <repo-url>
cd ad-agent-poc
```

### 2. Set up Python environment
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Set up Node (Hyperframes layer)
```bash
cd hyperframes && npm install && cd ..
```

### 4. Configure API keys
```bash
cp .env.example .env
# edit .env and fill in GOOGLE_API_KEY and FAL_KEY
```

### 5. Install system dependencies
```bash
# macOS
brew install tesseract ffmpeg

# Ubuntu/Debian
sudo apt-get install tesseract-ocr ffmpeg
```

### 6. Run the app
```bash
streamlit run app.py
```

---

## Project Layout

```
├── app.py                  # Streamlit entry point
├── config/
│   └── platforms.yaml      # Platform limits & creative specs (single source of truth)
├── services/               # Business logic (one file per concern)
│   ├── intake.py           # Document upload & quality check
│   ├── extraction.py       # LLM fact extraction & confirmation
│   ├── copy_writer.py      # LLM ad copy generation
│   ├── creative.py         # Image prep + Wan 2.2 + Hyperframes orchestration
│   └── validation.py       # OCR + rules-based validation
├── models/
│   ├── fact_sheet.py       # Pydantic models
│   └── db.py               # SQLite schema & helpers
├── hyperframes/
│   ├── render.js           # FFmpeg assembly CLI (called by Python)
│   └── package.json
├── prompts/
│   ├── extraction.txt      # LLM prompt — fact extraction
│   └── copy_writer.txt     # LLM prompt — ad copy
├── docs/                   # Architecture & design docs
├── uploads/                # Raw uploaded documents (git-ignored)
├── outputs/                # Generated creatives (git-ignored)
└── db/                     # SQLite database (git-ignored)
```

---

## Implementation Phases

| Phase | Status | Description |
|-------|--------|-------------|
| 1 | ✅ Done | Project setup, config, env, directory structure |
| 2 | ⬜ | Pydantic models + SQLite schema |
| 3 | ⬜ | Document Intake Service |
| 4 | ⬜ | Fact Extraction Service (LLM) |
| 5 | ⬜ | Ad Copy Writer |
| 6 | ⬜ | Creative Generation Pipeline |
| 7 | ⬜ | Validation Service |
| 8 | ⬜ | Streamlit UI |
| 9 | ⬜ | Return Visit flow |

---

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `GROQ_API_KEY` | Groq LLM API key |
| `GROQ_MODEL` | Model to use (default: `llama-3.3-70b-versatile`) |
| `FAL_KEY` | fal.ai key for Wan 2.2 image-to-video |
| `UPLOAD_ROOT` | Override upload directory (default: `uploads/`) |
| `DB_PATH` | Override SQLite path (default: `db/database.db`) |
| `OUTPUT_ROOT` | Override output directory (default: `outputs/`) |
