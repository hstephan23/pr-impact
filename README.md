# PR Impact

**See what your pull request actually breaks** — before it ships.

PR Impact is a GitHub App that analyzes every pull request and posts a clear, visual comment showing the blast radius of your changes: which files are affected downstream, what architectural rules are violated, and where coupling risk is highest. No dashboards to check, no links to click — the insight is right there in the PR.

## Why

Code review tools show you *what changed*. PR Impact shows you *what your changes touch*. A 10-line edit in a utility file might ripple through 40% of your codebase. A new import might violate your team's architectural layering. A deleted file might break a dependency chain three levels deep. PR Impact catches all of this automatically and tells you about it in plain language, right on the PR.

## How It Works

```
PR opened/updated → GitHub webhook fires → PR Impact clones both branches
→ Builds dependency graphs for base and head → Diffs the graphs
→ Generates a rich Markdown comment → Posts it on the PR
```

### What the comment includes

- **Change summary** — files added, removed, and modified with their dependency counts
- **Blast radius** — every file transitively affected by the changes, grouped by depth
- **New cycles** — circular dependencies introduced by the PR
- **Architectural violations** — imports that break your team's layer rules (e.g. a UI file importing from the data layer)
- **Coupling alerts** — changes that increase tight coupling between directories
- **Risk score** — a single number (0-100) summarizing the structural risk of the PR

### Example comment

```markdown
## PR Impact

**Risk: 34/100** · 3 files changed · 12 files in blast radius · 1 new violation

### Blast Radius
`src/utils/auth.ts` (modified) affects 12 downstream files:
  → src/api/client.ts → src/api/users.ts → src/pages/profile.tsx
  → src/api/client.ts → src/api/posts.ts → src/pages/feed.tsx
  → ... and 6 more

### Architectural Violations
⚠ `src/data/userCache.ts` now imports from `src/ui/components/Avatar.tsx`
  → data layer should not depend on ui layer

### New Cycles
None introduced — nice work.
```

## Architecture

```
pr-impact/
├── engine/                  # Graph analysis engine (from DepGraph)
│   ├── graph.py             # Graph builder, cycle detection, metrics
│   ├── parsers.py           # Language-specific import resolution (18 languages)
│   └── churn.py             # Git commit frequency analysis
│
├── app/
│   ├── main.py              # FastAPI entrypoint
│   ├── config.py            # Environment config and secrets
│   │
│   ├── github/              # GitHub App integration
│   │   ├── auth.py          # JWT signing, installation tokens
│   │   ├── webhooks.py      # Webhook receiver and event routing
│   │   └── client.py        # GitHub API wrapper (repos, PRs, comments)
│   │
│   ├── analysis/            # PR-specific analysis pipeline
│   │   ├── pipeline.py      # Orchestrates clone → build → diff → score
│   │   ├── diff.py          # Graph diffing (added/removed nodes and edges)
│   │   ├── blast_radius.py  # Transitive impact calculation
│   │   ├── violations.py    # Architectural rule checking
│   │   └── risk.py          # Risk scoring algorithm
│   │
│   ├── renderer/            # Comment generation
│   │   ├── markdown.py      # Markdown comment builder
│   │   └── templates/       # Jinja2 templates for comment sections
│   │       ├── comment.md.j2
│   │       ├── blast_radius.md.j2
│   │       └── violations.md.j2
│   │
│   └── workers/             # Background job processing
│       ├── queue.py         # Job queue (Redis-backed)
│       └── analyzer.py      # Worker that processes PR analysis jobs
│
├── tests/
│   ├── conftest.py          # Shared fixtures (mock repos, sample graphs)
│   ├── test_webhooks.py     # Webhook signature verification, event routing
│   ├── test_pipeline.py     # End-to-end analysis pipeline
│   ├── test_diff.py         # Graph diff logic
│   ├── test_blast_radius.py # Transitive impact calculation
│   ├── test_risk.py         # Risk scoring
│   └── test_renderer.py     # Markdown output formatting
│
├── .env.example             # Required environment variables
├── Dockerfile               # Production container
├── docker-compose.yml       # Local dev (app + Redis)
├── pyproject.toml           # Project metadata and dependencies
├── Makefile                 # Dev commands (test, lint, run, deploy)
└── README.md
```

## Supported Languages

PR Impact inherits DepGraph's parser suite — 18 languages out of the box:

JavaScript/TypeScript, Python, Java, Go, Rust, C/C++, C#, Swift, Kotlin, Scala, Ruby, PHP, Dart, Elixir, Lua, Zig, Haskell, R

## Configuration

Teams configure PR Impact through a `.pr-impact.yml` file in their repo root:

```yaml
# Which directories to analyze (default: entire repo)
paths:
  - src/
  - lib/

# Language detection (default: auto)
language: auto

# Architectural layers (top = highest level, bottom = lowest)
# Imports going "upward" are flagged as violations.
layers:
  - ui
  - api
  - service
  - data
  - util

# Thresholds for risk scoring
thresholds:
  blast_radius_warn: 10    # Flag PRs affecting >10 files
  blast_radius_critical: 30
  max_depth: 8             # Warn on deep dependency chains
  cycle_tolerance: 0       # Any new cycle is flagged

# What to include in the comment
comment:
  blast_radius: true
  violations: true
  cycles: true
  risk_score: true
  coupling_alerts: true

# Ignore patterns
ignore:
  - "**/*.test.*"
  - "**/__mocks__/**"
  - "**/generated/**"
```

## Setup

### 1. Install the GitHub App

Visit **[pr-impact.dev/install](https://pr-impact.dev/install)** and grant access to your repositories.

### 2. (Optional) Add configuration

Create `.pr-impact.yml` in your repo root. Without it, PR Impact uses sensible defaults — analyze everything, auto-detect language, flag all new cycles and violations.

### 3. Open a PR

That's it. PR Impact comments automatically on every pull request.

## Local Development

```bash
# Clone and install
git clone https://github.com/harrisonstephan/pr-impact.git
cd pr-impact
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Set up environment
cp .env.example .env
# Fill in GITHUB_APP_ID, GITHUB_PRIVATE_KEY, GITHUB_WEBHOOK_SECRET

# Start services
docker compose up -d redis
make dev     # Runs FastAPI on :8000 with hot reload

# Run tests
make test

# Lint
make lint
```

## Deployment

PR Impact is designed to run as a single container + Redis. Deploy anywhere that runs Docker:

```bash
docker compose up -d
```

For production, you'll need:
- A publicly reachable URL for GitHub webhooks
- Redis for the job queue
- The GitHub App private key as an environment variable

## Roadmap

- [x] GitHub App webhook integration
- [x] Graph diffing and blast radius
- [x] Architectural violation detection
- [x] Risk scoring
- [x] Markdown comment generation
- [ ] Caching (skip re-analysis if no structural changes)
- [ ] GitLab and Bitbucket support
- [ ] Hosted dashboard with historical trends
- [ ] Slack/Teams notifications for high-risk PRs
- [ ] Custom rules engine (beyond layer checking)
- [ ] PR size recommendations based on blast radius

## Built With

- [FastAPI](https://fastapi.tiangolo.com/) — async web framework
- [DepGraph engine](https://github.com/harrisonstephan/DepGraph) — graph analysis and 18-language parser suite
- [Redis](https://redis.io/) + [ARQ](https://arq-docs.helpmanual.io/) — background job processing
- [Jinja2](https://jinja.palletsprojects.com/) — comment templating

## License

MIT
