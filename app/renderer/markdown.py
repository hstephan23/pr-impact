"""Markdown comment renderer.

Takes an AnalysisResult and produces the Markdown body for the GitHub PR comment.
Uses Jinja2 templates for clean separation of logic and presentation.
"""

import os

from jinja2 import Environment, FileSystemLoader

from app.analysis.pipeline import AnalysisResult

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
_env = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


def render_comment(result: AnalysisResult) -> str:
    """Render the full PR comment from an analysis result."""
    template = _env.get_template("comment.md.j2")
    return template.render(r=result)


def render_no_changes() -> str:
    """Render a minimal comment when no structural changes are detected."""
    return (
        "## PR Impact\n\n"
        "No structural dependency changes detected. "
    )
