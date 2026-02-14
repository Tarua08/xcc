# X Content Agent System

A human-in-the-loop AI content agent that collects AI/tech signals, generates
draft X (Twitter) posts, and queues them for manual approval via a web dashboard.

## Architecture Overview

```
Cloud Scheduler (daily cron)
        |
        v
  Cloud Run Service
        |
        v
  PipelineOrchestrator (SequentialAgent)
   |-> CollectorAgent   -- fetches signals from 4 sources
   |-> RankerAgent      -- scores & shortlists top items
   |-> DraftingAgent    -- generates 2 drafts per item
   |-> QualityGuardAgent -- validates content quality
        |
        v
  Firestore (items / drafts collections)
        |
        v
  Approval UI (FastAPI on Cloud Run)
   - View / Edit / Approve / Reject drafts
   - Add human signature lines
   - Weekly "Ready to Post" list
```

## Design Decisions & Reasoning

### Why Google ADK?

ADK provides a structured way to compose agents with:
- Deterministic workflow orchestration (SequentialAgent) for the pipeline
- LLM-powered agents for intelligent tasks (ranking, drafting)
- Built-in callback/guardrail hooks for quality enforcement
- Shared session state for inter-agent communication
- Tool abstraction that auto-generates schemas from Python functions

### Agent Design

Each agent is an `LlmAgent` with specific tools, wrapped in a `SequentialAgent`
pipeline. Agents communicate via session state using `output_key`:

1. **CollectorAgent** - Uses function tools to fetch from GitHub Trending,
   Hacker News, arXiv, and RSS feeds. Outputs raw signal items to state.
   Model: gemini-2.0-flash (cheap, classification-grade task).

2. **RankerAgent** - Scores items 0-100 on relevance to target topics
   (AI agents, RAG, eval frameworks, deployments, DB-aware agents).
   Shortlists top 10. Model: gemini-2.0-flash.

3. **DraftingAgent** - Generates 2 draft variants per shortlisted item.
   Each draft must include a concrete use case, experiment idea, or tradeoff.
   Model: gemini-2.5-flash (stronger model for quality output).

4. **QualityGuardAgent** - Reviews each draft against content quality rules.
   Rejects drafts with hype language, fabricated metrics, or vague claims.
   Model: gemini-2.0-flash.

5. **WeeklySchedulerAgent** - Compiles approved drafts into a weekly posting
   schedule. Runs on-demand from the UI.

### Why Not Auto-Post?

MVP mandates human approval. The system produces a "Ready to Post" list that
you copy-paste. This prevents:
- Accidental publication of low-quality content
- Brand risk from AI hallucinations
- Loss of authentic voice

### Cost Optimization Strategy

| Decision | Reasoning |
|---|---|
| Daily fetch, not hourly | Signals don't change fast enough to justify 24x cost |
| Rank before drafting | LLM drafting is the most expensive step; only draft top 10 |
| gemini-2.0-flash for ranking | Classification is simple; cheapest model suffices |
| gemini-2.5-flash for drafting | Quality matters for output; mid-tier model balances cost/quality |
| Max 10 items/day drafted | Hard cap on LLM calls: 10 items x 2 drafts = 20 calls/day |
| Concise prompts | Shorter prompts = fewer input tokens = lower cost |
| No embeddings | Keyword + LLM scoring is sufficient for this scale |
| Response token limits | Cap draft output at 300 tokens (~280 chars for X) |

**Estimated daily cost**: ~$0.05-0.15/day (20 flash calls + 20 ranking calls)

### Security Model

- **No secrets in code**: All API keys and credentials via Secret Manager
- **IAM least privilege**: Each service gets only the permissions it needs
- **Input validation**: All external data sanitized before LLM prompts
- **Rate limiting**: Approval UI endpoints rate-limited (10 req/min)
- **Prompt injection defense**: External content wrapped in delimiters, never
  interpolated into system prompts directly
- **Factual grounding**: Drafts must cite source material; no fabrication

### Data Model (Firestore)

```
items/                          # Raw collected signals
  {url_hash}/
    url: string
    title: string
    source: string              # "github" | "hackernews" | "arxiv" | "rss"
    description: string
    collected_at: timestamp
    metadata: map

drafts/                         # Generated draft posts
  {draft_id}/
    item_id: string             # FK to items/{url_hash}
    variant: int                # 1 or 2
    content: string             # The draft text
    status: string              # "pending" | "approved" | "rejected"
    quality_score: float
    quality_notes: string
    human_lines: string         # Human-added signature lines
    created_at: timestamp
    reviewed_at: timestamp
    review_notes: string
```

### Idempotency

- Item IDs are SHA-256 hashes of the URL (deterministic, dedup-safe)
- Draft IDs are `{item_id}_{variant}` (deterministic per item+variant)
- Re-running the pipeline on the same day skips already-collected items
- Firestore writes use `set()` with merge for safe re-runs

## Deployment

See `infra/` directory for:
- Dockerfile
- Cloud Run service configuration
- Cloud Scheduler job setup
- Secret Manager setup guide

## Running Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export GOOGLE_CLOUD_PROJECT=your-project-id
export FIRESTORE_EMULATOR_HOST=localhost:8080  # optional, for local dev

# Run the pipeline
python -m x_content_agent.main

# Run the approval UI
python -m x_content_agent.services.approval_ui.app
```

## Testing

```bash
pytest x_content_agent/tests/ -v
```
