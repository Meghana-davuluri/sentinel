#!/usr/bin/env bash
# Deploy the Sentinel webhook to Cloud Run.
#
# Prerequisites (run once):
#   gcloud auth login
#   gcloud config set project <YOUR_PROJECT_ID>
#   gcloud services enable run.googleapis.com cloudbuild.googleapis.com
#
# Required env vars (set before running, do NOT commit real values):
#   GOOGLE_API_KEY          Gemini key for the reviewer agent
#   GITHUB_WEBHOOK_SECRET   shared secret you also set on the GitHub webhook
#   GH_TOKEN                a token that can read/comment on the target repo
#
# Usage:
#   GOOGLE_API_KEY=... GITHUB_WEBHOOK_SECRET=... GH_TOKEN=... ./deploy_webhook.sh
set -euo pipefail

SERVICE="sentinel-webhook"
REGION="${REGION:-us-central1}"

: "${GOOGLE_API_KEY:?set GOOGLE_API_KEY}"
: "${GITHUB_WEBHOOK_SECRET:?set GITHUB_WEBHOOK_SECRET}"
: "${GH_TOKEN:?set GH_TOKEN}"

gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_GENAI_USE_VERTEXAI=FALSE" \
  --set-env-vars "GOOGLE_API_KEY=${GOOGLE_API_KEY}" \
  --set-env-vars "GITHUB_WEBHOOK_SECRET=${GITHUB_WEBHOOK_SECRET}" \
  --set-env-vars "GH_TOKEN=${GH_TOKEN}"

echo ""
echo "Deployed. The webhook URL is the service URL above, with path /webhook."
echo "Add it as a webhook on the target repo:"
echo "  Settings -> Webhooks -> Add webhook"
echo "  Payload URL:  <service-url>/webhook"
echo "  Content type: application/json"
echo "  Secret:       <your GITHUB_WEBHOOK_SECRET>"
echo "  Events:       Pull requests"
