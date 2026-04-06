# Engine module — graph analysis core from DepGraph.
#
# This package contains the vendored graph engine:
#   graph.py   — graph builder, cycle detection (Tarjan's SCC), per-node metrics
#   parsers.py — language-specific import resolution (18 languages)
#   churn.py   — git commit frequency analysis
#
# adapter.py provides a clean interface for pr-impact to call the engine
# without coupling to DepGraph's internal conventions.
#
# To update, copy the latest versions from the DepGraph repo.
