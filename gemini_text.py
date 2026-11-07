"""
Gemini text generation helper
=============================
One place for text/JSON calls to Gemini, tried in this order:

  1. Vertex AI with the service account (GCP_PROJECT_ID + GOOGLE_APPLICATION_CREDENTIALS),
     on the "global" endpoint first, then GCP_LOCATION.
  2. The Gemini API with GEMINI_API_KEY (generativelanguage.googleapis.com).

Models are tried in order: GEMINI_TEXT_MODEL (if set), then DEFAULT_TEXT_MODELS.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

DEFAULT_TEXT_MODELS = ["gemini-3-flash-preview", "gemini-2.5-flash", "gemini-flash-latest"]


def _models() -> List[str]:
    override = os.getenv("GEMINI_TEXT_MODEL", "").strip()
    return ([override] if override else []) + [m for m in DEFAULT_TEXT_MODELS if m != override]


def _vertex_token() -> Optional[str]:
    try:
        import google.auth
        from google.auth.transport.requests import Request

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(Request())
        return creds.token
    except Exception:
        return None


def _extract_text(resp_json: Dict[str, Any]) -> str:
    parts = resp_json["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


def generate_text(
    prompt: str,
    system_prompt: Optional[str] = None,
    api_key: Optional[str] = None,
    json_mode: bool = False,
    temperature: float = 0.4,
    max_output_tokens: int = 8192,
    timeout: int = 120,
) -> Tuple[str, str]:
    """Return (text, "<backend>/<model>"). Raises RuntimeError listing every failure."""
    body: Dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_output_tokens},
    }
    if system_prompt:
        body["systemInstruction"] = {"parts": [{"text": system_prompt}]}
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"

    errors: List[str] = []

    # 1. Vertex AI (service account)
    project = os.getenv("GCP_PROJECT_ID", "").strip()
    token = _vertex_token() if project else None
    if project and token:
        location = os.getenv("GCP_LOCATION", "us-central1").strip() or "us-central1"
        for where in dict.fromkeys(["global", location]):
            host = "aiplatform.googleapis.com" if where == "global" else f"{where}-aiplatform.googleapis.com"
            for model in _models():
                url = f"https://{host}/v1/projects/{project}/locations/{where}/publishers/google/models/{model}:generateContent"
                try:
                    r = requests.post(url, headers={"Authorization": f"Bearer {token}"}, json=body, timeout=timeout)
                except requests.RequestException as exc:
                    errors.append(f"vertex/{where}/{model}: {exc.__class__.__name__}")
                    continue
                if r.status_code == 200:
                    return _extract_text(r.json()), f"vertex-{where}/{model}"
                errors.append(f"vertex/{where}/{model}: HTTP {r.status_code}")

    # 2. Gemini API key
    key = (api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    if key and not key.startswith("your_"):
        for model in _models():
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            try:
                r = requests.post(url, json=body, timeout=timeout)
            except requests.RequestException as exc:
                errors.append(f"api-key/{model}: {exc.__class__.__name__}")
                continue
            if r.status_code == 200:
                return _extract_text(r.json()), f"api-key/{model}"
            reason = ""
            try:
                reason = r.json()["error"]["details"][0].get("reason", "")
            except Exception:
                pass
            errors.append(f"api-key/{model}: HTTP {r.status_code}{' ' + reason if reason else ''}")

    if not errors:
        raise RuntimeError("no Gemini credentials (set GCP_PROJECT_ID + service account, or GEMINI_API_KEY)")
    # Keep the message short: first and last few failures
    shown = errors if len(errors) <= 4 else errors[:2] + ["…"] + errors[-2:]
    raise RuntimeError("Gemini unavailable: " + "; ".join(shown))


def generate_json(prompt: str, system_prompt: Optional[str] = None, **kwargs: Any) -> Tuple[Any, str]:
    text, used = generate_text(prompt, system_prompt=system_prompt, json_mode=True, **kwargs)
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    return json.loads(cleaned), used


def credentials_available(api_key: Optional[str] = None) -> bool:
    key = (api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    has_key = bool(key) and not key.startswith("your_")
    has_vertex = bool(os.getenv("GCP_PROJECT_ID", "").strip() and os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))
    return has_key or has_vertex
