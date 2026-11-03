# Festive Real-Estate Video Ad Generator (Veo 3.1 Fast) 🎬✨

An end-to-end Python application that transforms any property's architectural renders, project details JSON, and developer logo into a high-impact, festival-themed promotional video ad (10–60s) using the **Google Gemini API (Veo 3.1 Fast)**, **Pillow**, and **FFmpeg**.

---

## 🌟 Key Features

1. **Any Real-Estate Project (Zero Hardcoding)**:
   - Reads project JSON schema dynamically (`project.name`, `promoter`, `units`, `brand.colours`, `brand.fonts`, `disclaimers`, etc.).
   - Strictly enforces mandatory **RERA Registration Number** (`rera.number`) before any generation can occur.
   - Formats Indian prices automatically (e.g. `9600000` → `₹96 Lakh`, `14200000` → `₹1.42 Cr`).

2. **Smart Scene Planner (10–60 Seconds)**:
   - Generates non-AI brand **End Card** (3s if $\le$15s, 4s if >15s) with Pillow/FFmpeg.
   - Fills remaining duration with native Veo clips (4, 6, or 8s).
   - Solves clip combinations to account for **0.5s crossfades** ensuring final video length matches user request within $\pm 1$s.
   - Prioritizes: Opening exterior render drone push-in → Interior & Amenity renders → Festival lifestyle sequences.

3. **Festival Celebration Themes**:
   - Themes supported: **Diwali, Ugadi, Dussehra, Ganesh Chaturthi, Onam, Pongal/Sankranti, Christmas, Eid, New Year, None**.
   - Generates culturally authentic decor, lighting, and attire prompts while preserving building architecture exactly.
   - When `"None"` is selected, creates an elegant non-festive architectural ad in warm golden-hour light.

4. **Continuous Soundtrack**:
   - Generates an instrumental Indian festive music bed via Google Lyria or rich procedural acoustic synthesis.
   - Loops/trims user-uploaded audio with 1s fade-in and 2s fade-out.

5. **Automated Legal Overlays & Verification**:
   - **RERA Bar**: Black 45% translucent bar at the bottom ($\ge 2.5\%$ video height) with centered white text: `"RERA No: {number} | *T&C Apply"`.
   - **Disclaimers**: Compact disclaimer text burned directly above RERA bar.
   - **Render Tag**: `"Artist's impression"` badge on render scenes.
   - **Draft Protection**: Burns `"DRAFT – NOT FOR PUBLICATION"` across center if project status is unverified.
   - **Post-export check**: Validates duration within $\pm 1$s and samples 1 frame/second to verify the RERA bar across all frames.

6. **Safety & Cost Transparency**:
   - "Preview plan & cost" shows billed seconds and estimated cost upfront without making paid API calls.
   - Clip-level caching in `./cache` keyed by sha256 hash of prompt, image bytes, and parameters.
   - Retry logic up to 2 times on Veo calls.
   - Dry-run / Simulation mode for complete local testing without API key or charges.

---

## 🚀 Setup & Installation

### 1. Prerequisites
- **Python 3.10+**
- **FFmpeg & FFprobe** installed:
  ```bash
  # macOS (Homebrew)
  brew install ffmpeg
  ```

### 2. Install Dependencies
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Environment Variables
Copy `.env.example` to `.env` and set your Google Gemini API key:
```bash
cp .env.example .env
```
Edit `.env`:
```bash
GEMINI_API_KEY=AIzaSy...
```
*(Leave blank to run in Dry-Run / Simulation mode at 0 cost).*

---

## 💻 Usage

### A. Streamlit Web App (Recommended)
Launch the interactive web UI:
```bash
streamlit run app.py
```
1. Set video duration (10–60s) and select a Festival theme.
2. Choose Aspect Ratio (`16:9` or `9:16`) and Resolution (`1080p` or `720p`).
3. Upload your project details JSON, logo PNG, and render images (or click **"Load Aurelia Heights Sample Assets"** for a 1-click test).
4. Click **"📋 Preview Plan & Cost"** to inspect scene prompts, timings, and estimated cost without any API calls.
5. Click **"🚀 Generate Festive Video Ad"** to render and download your broadcast-ready video.

---

### B. Command-Line Interface (CLI)
Run batch generations directly from the terminal:

```bash
# Dry-run test (simulation mode, 0 API cost)
python main.py \
  --duration 30 \
  --festival Diwali \
  --aspect 16:9 \
  --resolution 1080p \
  --project inputs/project.json \
  --logo inputs/logo.png \
  --renders inputs/renders/ \
  --dry-run

# Live video generation with Google Veo 3.1 Fast
python main.py \
  --duration 30 \
  --festival Diwali \
  --aspect 16:9 \
  --resolution 1080p \
  --project inputs/project.json \
  --logo inputs/logo.png \
  --renders inputs/renders/
```

#### CLI Arguments:
| Argument | Description | Default |
| :--- | :--- | :--- |
| `--duration` | Length in seconds (10 to 60) | `30` |
| `--festival` | Festival celebration theme (`Diwali`, `Ugadi`, `Dussehra`, `Christmas`, etc.) | `Diwali` |
| `--aspect` | Video aspect ratio (`16:9` for YouTube, `9:16` for Reels/Shorts) | `16:9` |
| `--resolution`| Video resolution (`1080p`, `720p`) | `1080p` |
| `--project` | Path to project details JSON (Required, enforces RERA number) | — |
| `--logo` | Path to developer logo PNG (Required) | — |
| `--renders` | Directory containing render images & optional `renders.json` | — |
| `--music` | Optional path to custom audio track | Procedural / Lyria |
| `--dry-run` | Run local simulation without making paid API calls | `False` |

---

## 📁 Project Architecture

```
.
├── app.py              # Streamlit Web UI with live preview and video player
├── main.py             # CLI application entrypoint
├── project_data.py     # JSON parser, Indian price formatter, RERA validation
├── planner.py          # Scene planner, duration solver, festive prompt generator
├── veo_client.py       # Veo 3.1 Fast client with caching and retry logic
├── music.py            # Audio composer with Lyria and acoustic synthesizer fallback
├── endcard.py          # Non-AI Pillow + FFmpeg brand end card generator
├── overlays.py         # FFmpeg RERA bar, disclaimers, crossfades & frame verification
├── inputs/             # Sample datasets (Aurelia Heights JSON, logo, renders)
│   ├── project.json
│   ├── logo.png
│   └── renders/
│       ├── dusk_exterior.png
│       ├── living_room.png
│       ├── master_bedroom.png
│       ├── facade_entrance.png
│       └── renders.json
├── cache/              # Video & audio clip cache
├── output/             # Final generated MP4 ad creatives
├── requirements.txt    # Project dependencies
├── .env.example        # Environment variable template
└── README.md
```

---

## ⚖️ RERA Compliance & Legal Guardrails
1. **Mandatory RERA Verification**: Generation is strictly blocked if `rera.number` is missing or empty.
2. **Persistent Bar**: The RERA bar (`RERA No: {number} | *T&C Apply`) and disclaimers are burned on every single frame.
3. **Automated Verification**: Every exported ad is verified post-render to confirm duration $\pm 1$s and frame-by-frame presence of RERA text.
4. **Draft Protection**: If `project.status != "verified"`, a semi-transparent `"DRAFT – NOT FOR PUBLICATION"` watermark is applied across the video.
