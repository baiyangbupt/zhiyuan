"""Unit tests for ExtractConfig in app.config module."""

from __future__ import annotations

import pytest

from app.config import ExtractConfig


class TestExtractConfig:
    """Tests for ExtractConfig."""

    def test_default_last_n_messages(self, monkeypatch):
        """Test default value for last_n_messages."""
        monkeypatch.delenv("EXTRACT_LAST_N_MESSAGES", raising=False)
        monkeypatch.setattr(
            "app.config.ExtractConfig.model_config",
            {**ExtractConfig.model_config, "env_file": None},
        )

        config = ExtractConfig()

        assert config.last_n_messages == 10

    def test_load_from_env(self, monkeypatch):
        """Test loading last_n_messages from environment variable."""
        monkeypatch.setenv("EXTRACT_LAST_N_MESSAGES", "20")
        monkeypatch.setattr(
            "app.config.ExtractConfig.model_config",
            {**ExtractConfig.model_config, "env_file": None},
        )

        config = ExtractConfig()

        assert config.last_n_messages == 20

    def test_extra_fields_ignored(self, monkeypatch):
        """Test that extra fields are ignored."""
        monkeypatch.setattr(
            "app.config.ExtractConfig.model_config",
            {**ExtractConfig.model_config, "env_file": None},
        )

        config = ExtractConfig(unknown_field="xxx")

        assert not hasattr(config, "unknown_field")
