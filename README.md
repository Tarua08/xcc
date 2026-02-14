# X Content Agent

A human-in-the-loop AI content agent that collects AI/tech signals from multiple sources, generates draft X (Twitter) posts, and queues them for manual approval via a web dashboard and Telegram bot.

## How It Works

```
Cloud Scheduler (daily cron)
        |
        v
  Cloud Run Service
        |
        v
  CollectorAgent   -> fetches signals from GitHub Trending, Hacker News, arXiv, RSS
  RankerAgent      -> scores & shortlists top 10 items
  DraftingAgent    -> generates 2 draft variants per item
  QualityGuardAgent -> validates content quality, rejects low-quality drafts
        |
        v
  Firestore (items / drafts)
        |
        v
  Approval UI (FastAPI)  +  Telegram Bot
  - View / Edit / Approve / Reject drafts
  - Weekly posting schedule
```

## Tech Stack

- **Orchestration**: [Google ADK](https://google.github.io/adk-docs/) (Agent Development Kit) with `SequentialAgent`
- **LLMs**: Gemini 2.0 Flash (collection, ranking, quality) + Gemini 2.5 Flash (drafting)
- **Storage**: Google Cloud Firestore
- **Deployment**: Google Cloud Run (scales to zero)
- **Approval**: FastAPI web dashboard + Telegram bot
- **Scheduling**: Cloud Scheduler (daily 8 AM UTC)

## Project Structure

```
x_content_agent/
  agents/           # ADK agent definitions (collector, ranker, drafter, quality guard)
  services/
    approval_ui/    # FastAPI dashboard with Jinja2 templates
    telegram_bot.py # Telegram bot for draft approvals
  shared/           # Firestore client, LLM client, models, utilities
  prompts/          # LLM prompt templates
  infra/            # Dockerfiles, deploy.sh, IAM setup
  tests/            # pytest test suite
  pipeline.py       # Pipeline orchestrator
  main.py           # Entry point (CLI + Cloud Run)
```

## Setup

### Prerequisites

- Python 3.11+
- Google Cloud project with Firestore, Secret Manager, and Vertex AI enabled

### Install

```bash
pip install -r requirements.txt
```

### Configure

```bash
# .env — non-secret config
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us-central1

# .env.local — secrets (gitignored)
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
X_API_KEY=...
X_API_KEY_SECRET=...
X_ACCESS_TOKEN=...
X_ACCESS_TOKEN_SECRET=...
```

### Run Locally

```bash
# Run the pipeline
python -m x_content_agent.main

# Run the approval UI
python -m x_content_agent.services.approval_ui.app
```

### Test

```bash
pytest x_content_agent/tests/ -v
```

## Deploy

```bash
./x_content_agent/infra/deploy.sh <project-id> [region]
```

This deploys two Cloud Run services:
1. **xcontent-pipeline** — daily content pipeline (scales to zero)
2. **xcontent-telegram** — Telegram bot for approvals (always-on, min 1 instance)

Secrets are mounted from Google Secret Manager at container startup.

## Cost

Estimated ~$0.05-0.15/day for LLM calls (capped at 20 drafts + 20 ranking calls using Flash models).

## Architecture Details

See [`x_content_agent/README.md`](x_content_agent/README.md) for detailed design decisions, data model, security model, and cost optimization strategy.
