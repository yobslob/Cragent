"""
Unified configuration system.

Three-layer merge: YAML file (base) -> ATA_* env vars (override) -> CLI args (final override).
"""

import json
import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


class Config(BaseModel):
    """All configuration for the Autonomous Testing Agent."""

    # Core Settings
    target_url: str = ""
    testing_instructions: str = ""

    # Depth & Batch Control
    max_depth: int = 5
    batch_size: int = 5
    max_retries: int = 3

    # Concurrency
    max_concurrency: int = 3
    inter_request_delay_ms: list[int] = Field(default_factory=lambda: [500, 1500])
    stagger_start_delay_ms: list[int] = Field(default_factory=lambda: [0, 2000])

    # Timeouts
    graph_timeout_seconds: int = 1800
    node_inactivity_timeout_seconds: int = 90
    node_absolute_timeout_seconds: int = 300
    navigation_timeout_seconds: int = 30
    max_graph_iterations: int = 50

    # LLM Configuration
    primary_model: str = "gpt-4o"
    fallback_model: str = "gpt-4o-mini"
    evaluator_model: str = "gpt-4o-mini"
    synthesizer_model: str = "gpt-4o-mini"
    temperature: float = 0.1
    llm_max_retries: int = 5
    llm_base_delay_seconds: int = 1
    rate_limit_min_wait_seconds: int = 3

    # Local Model Support
    ollama_base_url: str = "http://localhost:11434"
    ollama_num_ctx: int = 4096   # context window tokens for Ollama models

    # OpenRouter Support
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # Browser Configuration
    headless: bool = True
    browser: str = "chromium"
    stealth_enabled: bool = True
    viewport_width: int = 1280
    viewport_height: int = 720

    # Proxy Configuration
    proxy_list: list[str] = Field(default_factory=list)
    proxy_rotation: str = "round-robin"

    # Context Window Management
    a11y_tree_max_nodes: int = 150
    token_budget_past_results: int = 2000

    # Cookie Consent
    dismiss_cookie_consent: bool = True
    cookie_consent_timeout_ms: int = 3000

    # Authentication
    auth_bootstrap_enabled: bool = True
    login_url_patterns: list[str] = Field(
        default_factory=lambda: ["/login", "/signin", "/auth", "/sso"]
    )

    # Observability
    langsmith_enabled: bool = True
    langsmith_project: str = "autonomous-testing-agent"
    credential_redaction_enabled: bool = True

    # Output
    report_format: str = "markdown"
    report_output_path: str = "./test-report"


def _coerce_env_value(key: str, value: str, field_type: type):
    """Coerce an environment variable string to the appropriate Python type."""
    if field_type is bool:
        return value.lower() in ("true", "1", "yes")
    if field_type is int:
        return int(value)
    if field_type is float:
        return float(value)
    if field_type is list or str(field_type).startswith("list"):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return [v.strip() for v in value.split(",") if v.strip()]
    return value


def _get_field_base_type(field_info) -> type:
    """Extract the base type from a Pydantic field annotation."""
    annotation = field_info.annotation
    origin = getattr(annotation, "__origin__", None)
    if origin is list:
        return list
    if annotation is bool:
        return bool
    if annotation is int:
        return int
    if annotation is float:
        return float
    return str


def load_config(
    yaml_path: Optional[str] = None,
    cli_args: Optional[dict] = None,
) -> Config:
    """
    Load configuration with three-layer merge.

    Priority (highest to lowest):
    1. CLI arguments
    2. ATA_* environment variables
    3. YAML config file
    4. Pydantic model defaults
    """
    merged = {}

    # Layer 1: YAML file
    if yaml_path is None:
        default_path = Path(__file__).parent.parent / "config.yaml"
        if default_path.exists():
            yaml_path = str(default_path)

    if yaml_path and Path(yaml_path).exists():
        with open(yaml_path, "r") as f:
            yaml_data = yaml.safe_load(f) or {}
        merged.update(yaml_data)

    # Layer 2: Environment variables with ATA_ prefix
    field_info_map = Config.model_fields
    for env_key, env_value in os.environ.items():
        if env_key.startswith("ATA_"):
            config_key = env_key[4:].lower()
            if config_key in field_info_map:
                field_type = _get_field_base_type(field_info_map[config_key])
                merged[config_key] = _coerce_env_value(config_key, env_value, field_type)

    # Layer 3: CLI arguments (highest priority)
    if cli_args:
        for key, value in cli_args.items():
            if value is not None:
                merged[key] = value

    return Config(**merged)
