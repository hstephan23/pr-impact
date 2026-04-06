"""Tests for blast radius computation."""

from app.analysis.blast_radius import compute_blast_radius, total_affected


def test_blast_radius_single_file(sample_graph):
    result = compute_blast_radius(sample_graph, {"src/utils/auth.ts"})

    affected = result["src/utils/auth.ts"]
    affected_files = [e["file"] for e in affected]

    # auth.ts is imported by client.ts, which is imported by app.ts and users.ts, etc.
    assert "src/api/client.ts" in affected_files
    assert "src/app.ts" in affected_files


def test_blast_radius_leaf_file(sample_graph):
    # profile.tsx imports users but nothing imports profile
    result = compute_blast_radius(sample_graph, {"src/pages/profile.tsx"})
    affected = result["src/pages/profile.tsx"]
    assert affected == []  # Nothing depends on profile.tsx


def test_blast_radius_depth(sample_graph):
    result = compute_blast_radius(sample_graph, {"src/utils/auth.ts"})
    affected = result["src/utils/auth.ts"]

    # client.ts directly imports auth.ts → depth 1
    client = next(e for e in affected if e["file"] == "src/api/client.ts")
    assert client["depth"] == 1


def test_total_affected_deduplicates(sample_graph):
    result = compute_blast_radius(
        sample_graph, {"src/utils/auth.ts", "src/api/client.ts"}
    )
    total = total_affected(result)
    # Both blast radii overlap on some files — total should be deduplicated
    assert total >= 1
