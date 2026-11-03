"""
Tests for Unified Video Service
===============================
Run with: python tests/test_video_service.py

Tests:
  - Video service initialization and engine registration
  - Provider status checks for Wan 2.6 Flash, Veo 3.1 Fast, and HeyGen Avatar IV
  - VideoJobRequest construction and validation
  - Graceful handling of missing API keys and error reporting
  - Mock generation flows for Veo 3.1 Fast and HeyGen Avatar IV
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.video_service import (
    UnifiedVideoService,
    VideoJobRequest,
    VideoJobResponse,
    get_video_service,
    WanFlashEngine,
    VeoFastEngine,
    HeyGenAvatarEngine,
)


def test_video_service_initialization():
    service = get_video_service()
    assert "wan_flash" in service.engines, "wan_flash missing from service engines"
    assert "veo_fast" in service.engines, "veo_fast missing from service engines"
    assert "heygen_avatar" in service.engines, "heygen_avatar missing from service engines"
    assert isinstance(service.engines["wan_flash"], WanFlashEngine)
    assert isinstance(service.engines["veo_fast"], VeoFastEngine)
    assert isinstance(service.engines["heygen_avatar"], HeyGenAvatarEngine)
    print("✓ Video service initialization and engine registration passed")


def test_provider_statuses():
    service = get_video_service()
    statuses = service.get_statuses()
    assert len(statuses) == 3, f"Expected 3 provider statuses, got {len(statuses)}"
    
    status_dict = {s.provider_id: s for s in statuses}
    assert "wan_flash" in status_dict
    assert "veo_fast" in status_dict
    assert "heygen_avatar" in status_dict
    
    assert status_dict["wan_flash"].api_key_env == "FAL_KEY"
    assert status_dict["veo_fast"].api_key_env == "GEMINI_API_KEY"
    assert status_dict["heygen_avatar"].api_key_env == "HEYGEN_API_KEY"
    print("✓ Provider status checks passed")


def test_missing_key_graceful_handling():
    # Test Veo with no key
    with patch.dict(os.environ, {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}, clear=True):
        engine = VeoFastEngine({})
        req = VideoJobRequest(project_id="test_proj", aspect="9:16", duration=8)
        res = engine.generate(req)
        assert not res.success
        assert "not set" in (res.error or "").lower()

    # Test HeyGen with no key
    with patch.dict(os.environ, {"HEYGEN_API_KEY": ""}, clear=True):
        engine = HeyGenAvatarEngine({})
        req = VideoJobRequest(
            project_id="test_proj",
            aspect="9:16",
            duration=10,
            script_text="Hello world"
        )
        res = engine.generate(req)
        assert not res.success
        assert "not set" in (res.error or "").lower()
    print("✓ Missing API key graceful handling passed")


def test_heygen_requires_script():
    with patch.dict(os.environ, {"HEYGEN_API_KEY": "dummy_key"}):
        engine = HeyGenAvatarEngine({})
        req = VideoJobRequest(project_id="test_proj", aspect="9:16", duration=10, script_text=None)
        res = engine.generate(req)
        assert not res.success
        assert "requires a script" in (res.error or "").lower()
    print("✓ HeyGen script requirement validation passed")


def test_wan_flash_requires_image():
    with patch.dict(os.environ, {"FAL_KEY": "dummy_key"}):
        engine = WanFlashEngine({})
        req = VideoJobRequest(project_id="test_proj", aspect="9:16", duration=10, image_bytes=None)
        res = engine.generate(req)
        assert not res.success
        assert "requires render/image bytes" in (res.error or "").lower()
    print("✓ Wan Flash image requirement validation passed")


def test_mock_heygen_generate_flow():
    with patch.dict(os.environ, {"HEYGEN_API_KEY": "valid_mock_key"}):
        engine = HeyGenAvatarEngine({"default_avatar_id": "test_avatar", "default_voice_id": "test_voice"})
        
        with patch("requests.post") as mock_post, patch("requests.get") as mock_get, patch.object(engine, "_download_url"):
            mock_post_resp = MagicMock()
            mock_post_resp.status_code = 200
            mock_post_resp.json.return_value = {"code": 100, "data": {"video_id": "vid_123"}}
            mock_post.return_value = mock_post_resp

            mock_poll_resp = MagicMock()
            mock_poll_resp.status_code = 200
            mock_poll_resp.json.return_value = {
                "data": {"status": "completed", "video_url": "https://heygen.example.com/test.mp4"}
            }
            mock_get.return_value = mock_poll_resp

            req = VideoJobRequest(
                project_id="test_proj",
                aspect="9:16",
                duration=15,
                script_text="Welcome to luxury living at Aurelia."
            )
            
            res = engine.generate(req)
            assert res.success
            assert res.provider == "heygen_avatar"
            assert "heygen_avatar_9_16_15s.mp4" in (res.video_path or "")
    print("✓ Mock HeyGen Avatar IV generate flow passed")


def test_mock_veo_generate_flow():
    with patch.dict(os.environ, {"GEMINI_API_KEY": "valid_gemini_key"}):
        engine = VeoFastEngine({"model": "veo-3.1-fast"})

        with patch("requests.post") as mock_post, patch("requests.get") as mock_get, patch.object(engine, "_download_url"), patch("pathlib.Path.exists", return_value=True), patch("pathlib.Path.stat") as mock_stat:
            mock_stat.return_value.st_size = 50000

            mock_post_resp = MagicMock()
            mock_post_resp.status_code = 200
            mock_post_resp.json.return_value = {"name": "operations/veo-op-123"}
            mock_post.return_value = mock_post_resp

            mock_poll_resp = MagicMock()
            mock_poll_resp.status_code = 200
            mock_poll_resp.json.return_value = {
                "done": True,
                "response": {
                    "generateVideoResponse": {
                        "generatedSamples": [{"video": {"uri": "https://storage.googleapis.com/veo.mp4"}}]
                    }
                }
            }
            mock_get.return_value = mock_poll_resp

            req = VideoJobRequest(
                project_id="test_proj",
                aspect="9:16",
                duration=8,
                prompt="Cinematic real estate glide shot",
                image_bytes=b"dummy_image_data"
            )

            res = engine.generate(req)
            assert res.success
            assert res.provider == "veo_fast"
            assert res.duration == 8
            assert "veo_fast_9_16_8s.mp4" in (res.video_path or "")
    print("✓ Mock Veo 3.1 Fast generate flow passed")


if __name__ == "__main__":
    print("\nRunning Unified Video Service Tests...")
    test_video_service_initialization()
    test_provider_statuses()
    test_missing_key_graceful_handling()
    test_heygen_requires_script()
    test_wan_flash_requires_image()
    test_mock_heygen_generate_flow()
    test_mock_veo_generate_flow()
    print("\nAll 7 Unified Video Service tests passed successfully!\n")
