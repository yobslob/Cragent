"""Tests for configuration loading and merging."""

import os
import pytest
from src.config import Config, load_config


class TestConfigDefaults:
    def test_default_values(self):
        cfg = Config()
        assert cfg.max_depth == 5
        assert cfg.batch_size == 5
        assert cfg.max_concurrency == 3
        assert cfg.headless is True
        assert cfg.primary_model == "gpt-4o"
        assert cfg.temperature == 0.1

    def test_custom_values(self):
        cfg = Config(max_depth=10, headless=False)
        assert cfg.max_depth == 10
        assert cfg.headless is False


class TestLoadConfig:
    def test_load_with_defaults(self, tmp_path):
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("max_depth: 7\nbatch_size: 3\n")
        cfg = load_config(yaml_path=str(yaml_file))
        assert cfg.max_depth == 7
        assert cfg.batch_size == 3
        assert cfg.max_concurrency == 3  # Still default

    def test_cli_overrides_yaml(self, tmp_path):
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("max_depth: 7\n")
        cfg = load_config(
            yaml_path=str(yaml_file),
            cli_args={"max_depth": 12},
        )
        assert cfg.max_depth == 12

    def test_env_overrides_yaml(self, tmp_path, monkeypatch):
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("max_depth: 7\n")
        monkeypatch.setenv("ATA_MAX_DEPTH", "15")
        cfg = load_config(yaml_path=str(yaml_file))
        assert cfg.max_depth == 15

    def test_cli_overrides_env(self, tmp_path, monkeypatch):
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("max_depth: 7\n")
        monkeypatch.setenv("ATA_MAX_DEPTH", "15")
        cfg = load_config(
            yaml_path=str(yaml_file),
            cli_args={"max_depth": 20},
        )
        assert cfg.max_depth == 20

    def test_bool_env_coercion(self, monkeypatch):
        monkeypatch.setenv("ATA_HEADLESS", "false")
        cfg = load_config(yaml_path="nonexistent.yaml")
        assert cfg.headless is False

    def test_missing_yaml_uses_defaults(self):
        cfg = load_config(yaml_path="nonexistent.yaml")
        assert cfg.max_depth == 5
