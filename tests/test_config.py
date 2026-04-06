"""Tests for repo config parsing and validation."""

from app.analysis.config import parse_repo_config, RepoConfig


def test_none_returns_defaults():
    config = parse_repo_config(None)
    assert config.paths == ["."]
    assert config.language == "auto"
    assert config.layers == []
    assert config.blast_radius_warn == 10


def test_empty_dict_returns_defaults():
    config = parse_repo_config({})
    assert config.language == "auto"
    assert config.show_blast_radius is True


def test_valid_config():
    raw = {
        "paths": ["src/", "lib/"],
        "language": "typescript",
        "layers": ["UI", "Service", "Data"],
        "thresholds": {
            "blast_radius_warn": 5,
            "blast_radius_critical": 20,
        },
        "comment": {
            "coupling_alerts": False,
        },
        "ignore": ["**/*.test.*"],
    }
    config = parse_repo_config(raw)
    assert config.paths == ["src/", "lib/"]
    assert config.language == "typescript"
    assert config.layers == ["ui", "service", "data"]
    assert config.blast_radius_warn == 5
    assert config.blast_radius_critical == 20
    assert config.show_coupling_alerts is False
    assert config.ignore == ["**/*.test.*"]


def test_invalid_language_falls_back():
    config = parse_repo_config({"language": "fortran"})
    assert config.language == "auto"


def test_invalid_types_ignored():
    raw = {
        "paths": "not a list",
        "layers": 42,
        "thresholds": {"blast_radius_warn": "not an int"},
    }
    config = parse_repo_config(raw)
    assert config.paths == ["."]  # Default
    assert config.layers == []  # Default
    assert config.blast_radius_warn == 10  # Default


def test_negative_thresholds_ignored():
    raw = {"thresholds": {"blast_radius_warn": -5}}
    config = parse_repo_config(raw)
    assert config.blast_radius_warn == 10  # Default
