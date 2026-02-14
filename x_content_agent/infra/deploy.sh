#!/usr/bin/env bash
# Deployment script for X Content Agent to Google Cloud Run.
#
# Deploys two services:
#   1. xcontent-pipeline  — daily content pipeline (scales to zero)
#   2. xcontent-telegram  — Telegram bot for approvals (always-on)
#
# Secrets are mounted from Google Secret Manager at container startup.
#
# Usage: ./deploy.sh <project-id> [region]
# Example: ./deploy.sh xccc-487412 us-central1

set -euo pipefail

PROJECT_ID="${1:?Usage: deploy.sh <project-id> [region]}"
REGION="${2:-us-central1}"

PIPELINE_SERVICE="xcontent-pipeline"
TELEGRAM_SERVICE="xcontent-telegram"
SCHEDULER_JOB="xcontent-daily-pipeline"
REPO_NAME="xcontent"

echo "=== Deploying X Content Agent to $PROJECT_ID ($REGION) ==="

# ---------------------------------------------------------------------------
# 1. Enable required APIs
# ---------------------------------------------------------------------------
echo "--- Enabling APIs ---"
gcloud services enable \
    run.googleapis.com \
    firestore.googleapis.com \
    cloudscheduler.googleapis.com \
    secretmanager.googleapis.com \
    aiplatform.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    --project="$PROJECT_ID"

# ---------------------------------------------------------------------------
# 2. Create Artifact Registry repository (if not exists)
# ---------------------------------------------------------------------------
echo "--- Setting up Artifact Registry ---"
gcloud artifacts repositories create "$REPO_NAME" \
    --repository-format=docker \
    --location="$REGION" \
    --project="$PROJECT_ID" 2>/dev/null || echo "Artifact Registry repo already exists"

AR_PREFIX="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}"

# ---------------------------------------------------------------------------
# 3. Create Firestore database (if not exists)
# ---------------------------------------------------------------------------
echo "--- Setting up Firestore ---"
gcloud firestore databases create \
    --project="$PROJECT_ID" \
    --location="$REGION" \
    --type=firestore-native 2>/dev/null || echo "Firestore database already exists"

# ---------------------------------------------------------------------------
# 4. Create Secret Manager secrets (if not exists)
# ---------------------------------------------------------------------------
echo "--- Setting up Secret Manager ---"
SECRETS=(
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID
    X_API_KEY
    X_API_KEY_SECRET
    X_ACCESS_TOKEN
    X_ACCESS_TOKEN_SECRET
)

for secret in "${SECRETS[@]}"; do
    gcloud secrets create "$secret" --project="$PROJECT_ID" 2>/dev/null || true
done

echo "Ensure all secrets have values set. Example:"
echo "  echo -n 'VALUE' | gcloud secrets versions add SECRET_NAME --data-file=- --project=$PROJECT_ID"

# ---------------------------------------------------------------------------
# 5. Build and deploy Pipeline service (scales to zero)
# ---------------------------------------------------------------------------
echo ""
echo "--- Building Pipeline service ---"
cp x_content_agent/infra/Dockerfile Dockerfile
gcloud builds submit \
    --tag "${AR_PREFIX}/${PIPELINE_SERVICE}" \
    --project="$PROJECT_ID" \
    .
rm -f Dockerfile

echo "--- Deploying Pipeline service ---"
gcloud run deploy "$PIPELINE_SERVICE" \
    --image "${AR_PREFIX}/${PIPELINE_SERVICE}" \
    --platform managed \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --no-allow-unauthenticated \
    --memory 1Gi \
    --cpu 1 \
    --timeout 600 \
    --min-instances 0 \
    --max-instances 1 \
    --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLOUD_LOCATION=$REGION,GOOGLE_GENAI_USE_VERTEXAI=TRUE,LOG_LEVEL=INFO" \
    --set-secrets "TELEGRAM_BOT_TOKEN=TELEGRAM_BOT_TOKEN:latest,TELEGRAM_CHAT_ID=TELEGRAM_CHAT_ID:latest,X_API_KEY=X_API_KEY:latest,X_API_KEY_SECRET=X_API_KEY_SECRET:latest,X_ACCESS_TOKEN=X_ACCESS_TOKEN:latest,X_ACCESS_TOKEN_SECRET=X_ACCESS_TOKEN_SECRET:latest"

PIPELINE_URL=$(gcloud run services describe "$PIPELINE_SERVICE" \
    --region "$REGION" --project "$PROJECT_ID" \
    --format 'value(status.url)')

# ---------------------------------------------------------------------------
# 6. Build and deploy Telegram bot service (always-on)
# ---------------------------------------------------------------------------
echo ""
echo "--- Building Telegram bot service ---"
cp x_content_agent/infra/Dockerfile.telegram Dockerfile
gcloud builds submit \
    --tag "${AR_PREFIX}/${TELEGRAM_SERVICE}" \
    --project="$PROJECT_ID" \
    .
rm -f Dockerfile

echo "--- Deploying Telegram bot service ---"
gcloud run deploy "$TELEGRAM_SERVICE" \
    --image "${AR_PREFIX}/${TELEGRAM_SERVICE}" \
    --platform managed \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --no-allow-unauthenticated \
    --memory 512Mi \
    --cpu 1 \
    --timeout 300 \
    --min-instances 1 \
    --max-instances 1 \
    --no-cpu-throttling \
    --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLOUD_LOCATION=$REGION,LOG_LEVEL=INFO" \
    --set-secrets "TELEGRAM_BOT_TOKEN=TELEGRAM_BOT_TOKEN:latest,TELEGRAM_CHAT_ID=TELEGRAM_CHAT_ID:latest,X_API_KEY=X_API_KEY:latest,X_API_KEY_SECRET=X_API_KEY_SECRET:latest,X_ACCESS_TOKEN=X_ACCESS_TOKEN:latest,X_ACCESS_TOKEN_SECRET=X_ACCESS_TOKEN_SECRET:latest"

TELEGRAM_URL=$(gcloud run services describe "$TELEGRAM_SERVICE" \
    --region "$REGION" --project "$PROJECT_ID" \
    --format 'value(status.url)')

# ---------------------------------------------------------------------------
# 7. Set up Cloud Scheduler (daily 8 AM UTC)
# ---------------------------------------------------------------------------
echo ""
echo "--- Setting up Cloud Scheduler ---"

SA_NAME="xcontent-scheduler-sa"
SA_EMAIL="$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"

gcloud iam service-accounts create "$SA_NAME" \
    --display-name "X Content Scheduler SA" \
    --project "$PROJECT_ID" 2>/dev/null || true

gcloud run services add-iam-policy-binding "$PIPELINE_SERVICE" \
    --member "serviceAccount:$SA_EMAIL" \
    --role "roles/run.invoker" \
    --region "$REGION" \
    --project "$PROJECT_ID"

if gcloud scheduler jobs describe "$SCHEDULER_JOB" --location "$REGION" --project "$PROJECT_ID" &>/dev/null; then
    gcloud scheduler jobs update http "$SCHEDULER_JOB" \
        --location "$REGION" \
        --schedule "0 8 * * *" \
        --uri "${PIPELINE_URL}/run" \
        --http-method POST \
        --oidc-service-account-email "$SA_EMAIL" \
        --project "$PROJECT_ID"
else
    gcloud scheduler jobs create http "$SCHEDULER_JOB" \
        --location "$REGION" \
        --schedule "0 8 * * *" \
        --uri "${PIPELINE_URL}/run" \
        --http-method POST \
        --oidc-service-account-email "$SA_EMAIL" \
        --project "$PROJECT_ID"
fi

echo ""
echo "=== Deployment Complete ==="
echo "Pipeline service: $PIPELINE_URL"
echo "Telegram bot:     $TELEGRAM_URL"
echo "Scheduler:        Daily at 8:00 AM UTC"
echo ""
echo "Verification:"
echo "  gcloud run services list --project=$PROJECT_ID"
echo "  curl -X POST ${PIPELINE_URL}/run -H 'Authorization: Bearer \$(gcloud auth print-identity-token)'"
echo "  Send /drafts to @Xai-7 on Telegram"
echo "  gcloud run services logs read $TELEGRAM_SERVICE --region=$REGION --project=$PROJECT_ID"
