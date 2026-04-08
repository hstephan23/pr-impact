"""Markdown comment renderer.

Takes an AnalysisResult and produces the Markdown body for the GitHub PR comment.
Uses Jinja2 templates for clean separation of logic and presentation.

Every rendered comment starts with a hidden HTML marker so the bot can
reliably find and update its own comment — regardless of what visible
heading text the comment begins with.
"""

import os

from jinja2 import Environment, FileSystemLoader

from app.analysis.pipeline import AnalysisResult

# Hidden marker placed as the first line of every bot comment. It's an HTML
# comment so GitHub's markdown renderer hides it from users, but it's
# cheap to search for in the issue comments API response.
BOT_MARKER = "<!-- pr-impact-bot -->"

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
    return BOT_MARKER + "\n" + template.render(r=result)


def render_no_changes() -> str:
    """Render a minimal comment when no structural changes are detected."""
    return (
        f"{BOT_MARKER}\n"
        "## PR Impact\n\n"
        "No structural dependency changes detected.\n"
    )


def render_error(message: str, head_sha: str = "") -> str:
    """Render a comment explaining that analysis failed.

    Used by the worker when the pipeline raises. Keeps the error message
    short and wraps it in a collapsible block so it doesn't dominate the PR.
    """
    short_sha = head_sha[:7] if head_sha else ""
    sha_line = f" for `{short_sha}`" if short_sha else ""
    # Truncate the error to keep comments under GitHub's size cap.
    trimmed = (message or "unknown error").strip()
    if len(trimmed) > 1000:
        trimmed = trimmed[:1000] + "\n...[truncated]"
    return (
        f"{BOT_MARKER}\n"
        f"## PR Impact\n\n"
        f"**Analysis failed**{sha_line}.\n\n"
        f"PR Impact could not complete analysis for this PR. This is usually "
        f"transient — push a new commit to retry.\n\n"
        f"<details><summary>Error details</summary>\n\n"
        f"```\n{trimmed}\n```\n\n"
        f"</details>\n"
    )
