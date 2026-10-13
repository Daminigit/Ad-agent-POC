from dotenv import load_dotenv
load_dotenv()
from services.creative import assemble_reel

try:
    path = assemble_reel(
        project_id="test_render_123",
        clip_path="/Users/darshan/Documents/ad agent POC/Ad-agent-POC/outputs/6155c806-9ae3-426f-9fdd-7aada481191e/clips/fallback_9_16.jpg",
        rera_number="RERA 123",
        price_text="$1.2M",
        logo_path=None
    )
    print(f"Success: {path}")
except Exception as e:
    print(f"Error: {e}")
