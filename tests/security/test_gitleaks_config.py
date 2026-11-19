"""A custom configuration must extend, never replace, the standard secret rules."""
from pathlib import Path
import tomllib


def test_gitleaks_keeps_default_detection_rules():
    root = Path(__file__).resolve().parents[2]
    config = tomllib.loads((root / ".gitleaks.toml").read_text())
    assert config["extend"]["useDefault"] is True
    assert "paths" not in config.get("allowlist", {})
    assert config.get("allowlist", {}).get("regexes") == [r"(?m)^NTFY_REMINDER_DAYS=14$"]
