"""Repo config loading and validation.

Parses and validates the .pr-impact.yml file from a repo, falling back
to sensible defaults for anything missing or invalid.
"""

from dataclasses import dataclass, field
from typing import Optional

# Supported language codes for the "language" field
VALID_LANGUAGES = {
    "auto", "python", "py", "javascript", "js", "typescript", "ts",
    "java", "go", "rust", "c", "cpp", "c++", "csharp", "cs",
    "swift", "kotlin", "scala", "ruby", "php", "dart", "elixir",
    "lua", "zig", "haskell", "r",
}


@dataclass
class RepoConfig:
    """Validated repository configuration."""
    paths: list[str] = field(default_factory=lambda: ["."])
    language: str = "auto"
    layers: list[str] = field(default_factory=list)
    hide_system: bool = True
    hide_isolated: bool = False

    # Thresholds
    blast_radius_warn: int = 10
    blast_radius_critical: int = 30
    max_depth: int = 8
    cycle_tolerance: int = 0

    # Comment sections
    show_blast_radius: bool = True
    show_violations: bool = True
    show_cycles: bool = True
    show_risk_score: bool = True
    show_coupling_alerts: bool = True

    # Ignore patterns
    ignore: list[str] = field(default_factory=list)


def parse_repo_config(raw: Optional[dict]) -> RepoConfig:
    """Parse and validate a raw .pr-impact.yml dict into a RepoConfig.

    Handles missing fields, wrong types, and invalid values gracefully
    by falling back to defaults.

    Args:
        raw: Parsed YAML dict, or None if no config file exists.

    Returns:
        Validated RepoConfig instance.
    """
    if not raw or not isinstance(raw, dict):
        return RepoConfig()

    config = RepoConfig()

    # Paths
    paths = raw.get("paths")
    if isinstance(paths, list) and all(isinstance(p, str) for p in paths):
        config.paths = paths if paths else ["."]

    # Language
    lang = raw.get("language", "auto")
    if isinstance(lang, str) and lang.lower() in VALID_LANGUAGES:
        config.language = lang.lower()

    # Layers
    layers = raw.get("layers")
    if isinstance(layers, list) and all(isinstance(l, str) for l in layers):
        config.layers = [l.strip().lower() for l in layers if l.strip()]

    # Boolean flags
    if isinstance(raw.get("hide_system"), bool):
        config.hide_system = raw["hide_system"]
    if isinstance(raw.get("hide_isolated"), bool):
        config.hide_isolated = raw["hide_isolated"]

    # Thresholds
    thresholds = raw.get("thresholds", {})
    if isinstance(thresholds, dict):
        for key, attr in [
            ("blast_radius_warn", "blast_radius_warn"),
            ("blast_radius_critical", "blast_radius_critical"),
            ("max_depth", "max_depth"),
            ("cycle_tolerance", "cycle_tolerance"),
        ]:
            val = thresholds.get(key)
            if isinstance(val, int) and val >= 0:
                setattr(config, attr, val)

    # Comment section toggles
    comment = raw.get("comment", {})
    if isinstance(comment, dict):
        for key, attr in [
            ("blast_radius", "show_blast_radius"),
            ("violations", "show_violations"),
            ("cycles", "show_cycles"),
            ("risk_score", "show_risk_score"),
            ("coupling_alerts", "show_coupling_alerts"),
        ]:
            val = comment.get(key)
            if isinstance(val, bool):
                setattr(config, attr, val)

    # Ignore patterns
    ignore = raw.get("ignore")
    if isinstance(ignore, list) and all(isinstance(p, str) for p in ignore):
        config.ignore = ignore

    return config


def config_to_dict(config: RepoConfig) -> dict:
    """Convert a RepoConfig to a plain dict for passing to analysis functions."""
    return {
        "paths": config.paths,
        "language": config.language,
        "layers": config.layers,
        "hide_system": config.hide_system,
        "hide_isolated": config.hide_isolated,
        "thresholds": {
            "blast_radius_warn": config.blast_radius_warn,
            "blast_radius_critical": config.blast_radius_critical,
            "max_depth": config.max_depth,
            "cycle_tolerance": config.cycle_tolerance,
        },
        "ignore": config.ignore,
    }
