"""
Configuration for Poster Generator
==================================
Defines poster dimensions, festive prompt templates, pricing, and model IDs.
"""

from typing import Any, Dict

# Model Identifiers
IMAGE_MODEL_ID = "gemini-2.5-flash-image"  # Google Gemini Nano Banana Image Model
TEXT_MODEL_ID = "gemini-2.5-flash"         # Google Gemini Text Model

# Google API Pricing (USD)
IMAGE_PRICE_USD = 0.03       # $0.03 per generated image
TEXT_CALL_PRICE_USD = 0.0001 # Minimal token cost for headline generation

# Available Poster Dimensions
# Version 1 enables exactly TWO posters per run: Instagram Post and Story / WhatsApp.
# Extra sizes are disabled for now and can be toggled on without changing any logic.
SIZES: Dict[str, Dict[str, Any]] = {
    "instagram_post": {
        "id": "instagram_post",
        "name": "Instagram Post",
        "width": 1080,
        "height": 1350,
        "aspect_ratio": "4:5",
        "enabled": True,
        "description": "Standard Instagram portrait feed post (1080x1350)",
    },
    "story": {
        "id": "story",
        "name": "Story / WhatsApp",
        "width": 1080,
        "height": 1920,
        "aspect_ratio": "9:16",
        "enabled": True,
        "description": "Full-screen vertical story for Instagram, WhatsApp & Facebook (1080x1920)",
    },
    # Extra sizes (disabled in Version 1)
    "square": {
        "id": "square",
        "name": "Square Post",
        "width": 1080,
        "height": 1080,
        "aspect_ratio": "1:1",
        "enabled": False,
        "description": "Square feed poster (1080x1080)",
    },
    "facebook_linkedin": {
        "id": "facebook_linkedin",
        "name": "Facebook / LinkedIn",
        "width": 1200,
        "height": 628,
        "aspect_ratio": "1.91:1",
        "enabled": False,
        "description": "Landscape banner post (1200x628)",
    },
    "print_a4": {
        "id": "print_a4",
        "name": "Print A4",
        "width": 2480,
        "height": 3508,
        "aspect_ratio": "1:1.414",
        "enabled": False,
        "description": "High-resolution print flyer (A4 300 DPI)",
    },
}

# Festive Elements Mapping per Festival
FESTIVAL_ELEMENTS: Dict[str, str] = {
    "Diwali": "warm golden fairy lights on the balconies, glowing lanterns, soft fireworks in a deep-blue dusk sky, lit brass diyas with marigold flowers in the foreground",
    "Ugadi": "mango-leaf torans, marigold garlands, a colourful rangoli in the foreground, bright morning light",
    "Dussehra": "marigold garlands, warm lamps, festive evening glow",
    "Ganesh Chaturthi": "marigold garlands, lit lamps and flowers in the foreground (no idol on or in front of the building)",
    "Onam": "a colourful pookalam flower carpet in the foreground, golden afternoon light",
    "Pongal/Sankranti": "sugarcane, a rangoli/kolam, colourful kites in a clear blue sky",
    "Christmas": "warm fairy lights, a decorated Christmas tree in the foreground, soft evening light",
    "Eid": "glowing lanterns and crescent-moon string lights, soft evening light",
    "New Year": "gentile fireworks and warm city lights at night",
    "None": "no decorations, beautiful golden-hour sky",
}

FESTIVALS = list(FESTIVAL_ELEMENTS.keys())
