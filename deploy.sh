#!/bin/bash
# Script de deploy para router-service

set -e

PROJECT_ID="falla-ai"
REGION="us-central1"
SERVICE_NAME="router-service"
SERVICE_ACCOUNT="router-service-sa@${PROJECT_ID}.iam.gserviceaccount.com"

echo "🚀 Iniciando deploy do ${SERVICE_NAME}..."

# Variáveis de ambiente
ENV_VARS="GCP_PROJECT=${PROJECT_ID},META_APP_SECRET_NAME=meta-app-secret,WPP_INBOUND_TOPIC=wpp-inbound-topic,DIALOGFLOW_LOCATION=us-central1,DIALOGFLOW_AGENT_ID=7f3455c5-9c67-4c51-a181-dfe3e5a60868,WHATSAPP_API_VERSION=v19.0"

# Deploy
echo "📦 Fazendo build e deploy..."
gcloud run deploy ${SERVICE_NAME} \
  --source . \
  --region ${REGION} \
  --service-account ${SERVICE_ACCOUNT} \
  --set-env-vars="${ENV_VARS}" \
  --allow-unauthenticated \
  --project=${PROJECT_ID} \
  --timeout=20m

# Obter URL do serviço
SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} \
  --region ${REGION} \
  --format="value(status.url)" \
  --project=${PROJECT_ID})

echo ""
echo "✅ Deploy concluído!"
echo "📍 URL do serviço: ${SERVICE_URL}"
echo ""
echo "📋 Próximos passos:"
echo "1. Configurar Pub/Sub Push Subscription:"
echo "   gcloud pubsub subscriptions create wpp-inbound-subscription \\"
echo "     --topic=wpp-inbound-topic \\"
echo "     --push-endpoint=${SERVICE_URL}/pubsub \\"
echo "     --push-auth-service-account=${SERVICE_ACCOUNT} \\"
echo "     --project=${PROJECT_ID}"
echo ""
echo "2. Configurar webhook na Meta:"
echo "   URL: ${SERVICE_URL}/webhook/whatsapp"

