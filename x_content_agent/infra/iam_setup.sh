#!/usr/bin/env bash
# IAM setup for least-privilege access.
# Run after deploy.sh to lock down permissions.
#
# Usage: ./iam_setup.sh <project-id>

set -euo pipefail

PROJECT_ID="${1:?Usage: iam_setup.sh <project-id>}"

echo "=== Setting up IAM roles (least privilege) ==="

# ---------------------------------------------------------------------------
# Pipeline service account (runs daily pipeline)
# ---------------------------------------------------------------------------
PIPELINE_SA="xcontent-pipeline-sa"
PIPELINE_EMAIL="$PIPELINE_SA@$PROJECT_ID.iam.gserviceaccount.com"

gcloud iam service-accounts create "$PIPELINE_SA" \
    --display-name "X Content Pipeline SA" \
    --project "$PROJECT_ID" 2>/dev/null || true

# Firestore read/write for items and drafts
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member "serviceAccount:$PIPELINE_EMAIL" \
    --role "roles/datastore.user"

# Vertex AI / Gemini API access
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member "serviceAccount:$PIPELINE_EMAIL" \
    --role "roles/aiplatform.user"

# Secret Manager access (read only)
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member "serviceAccount:$PIPELINE_EMAIL" \
    --role "roles/secretmanager.secretAccessor"

# ---------------------------------------------------------------------------
# Telegram bot service account (approval flow + posting to X)
# ---------------------------------------------------------------------------
TELEGRAM_SA="xcontent-telegram-sa"
TELEGRAM_EMAIL="$TELEGRAM_SA@$PROJECT_ID.iam.gserviceaccount.com"

gcloud iam service-accounts create "$TELEGRAM_SA" \
    --display-name "X Content Telegram Bot SA" \
    --project "$PROJECT_ID" 2>/dev/null || true

# Firestore read/write (for approving/rejecting drafts)
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member "serviceAccount:$TELEGRAM_EMAIL" \
    --role "roles/datastore.user"

# Secret Manager access (read bot token + X API keys)
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member "serviceAccount:$TELEGRAM_EMAIL" \
    --role "roles/secretmanager.secretAccessor"

# ---------------------------------------------------------------------------
# Scheduler service account (invokes pipeline)
# ---------------------------------------------------------------------------
SCHEDULER_SA="xcontent-scheduler-sa"
SCHEDULER_EMAIL="$SCHEDULER_SA@$PROJECT_ID.iam.gserviceaccount.com"

# Only needs Cloud Run invoker (already set in deploy.sh)

echo ""
echo "=== IAM Setup Complete ==="
echo "Pipeline SA:  $PIPELINE_EMAIL"
echo "   Roles: datastore.user, aiplatform.user, secretmanager.secretAccessor"
echo ""
echo "Telegram SA:  $TELEGRAM_EMAIL"
echo "   Roles: datastore.user, secretmanager.secretAccessor"
echo ""
echo "Scheduler SA: $SCHEDULER_EMAIL"
echo "   Roles: run.invoker (on pipeline service)"
