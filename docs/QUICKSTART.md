# Guia Rápido de Início

Este guia fornece os passos essenciais para colocar o sistema em funcionamento rapidamente.

## Pré-requisitos Rápidos

```bash
# 1. Autenticar no GCP
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

# 2. Habilitar APIs
gcloud services enable \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  pubsub.googleapis.com \
  secretmanager.googleapis.com \
  dialogflow.googleapis.com \
  firestore.googleapis.com
```

## Deploy Rápido (5 minutos)

### 1. Criar Recursos Base

```bash
# Tópico Pub/Sub
gcloud pubsub topics create wpp-inbound-topic

# Secret: Meta App Secret
echo -n "YOUR_META_APP_SECRET" | gcloud secrets create meta-app-secret --data-file=-

# Secret: Token de acesso (exemplo)
echo -n "YOUR_META_TOKEN" | gcloud secrets create meta-token-channel-123 --data-file=-
```

### 2. Configurar Firestore

Via console do Firestore ou CLI:

```bash
# Criar channel_mapping
gcloud firestore documents create channel_mappings/123456789 \
  --data='{"tenant_id":"tenant_123","credential_secret_name":"meta-token-channel-123"}'

# Criar tenant (via console ou código - veja DEPLOY.md)
```

### 3. Deploy handler-wpp

```bash
cd handler-wpp
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/handler-wpp

gcloud run deploy handler-wpp \
  --image gcr.io/YOUR_PROJECT_ID/handler-wpp \
  --region us-central1 \
  --set-env-vars="GCP_PROJECT=YOUR_PROJECT_ID,META_APP_SECRET_NAME=meta-app-secret,WPP_INBOUND_TOPIC=wpp-inbound-topic" \
  --allow-unauthenticated \
  --service-account=handler-wpp-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

### 4. Deploy router-wpp

```bash
# Do diretório raiz
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/router-wpp --config=router-wpp/cloudbuild.yaml

gcloud run deploy router-wpp \
  --image gcr.io/YOUR_PROJECT_ID/router-wpp \
  --region us-central1 \
  --set-env-vars="GCP_PROJECT=YOUR_PROJECT_ID,DIALOGFLOW_LOCATION=us-central1,DIALOGFLOW_AGENT_ID=YOUR_AGENT_ID" \
  --no-allow-unauthenticated \
  --service-account=router-wpp-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

### 5. Configurar Pub/Sub Push

```bash
ROUTER_URL=$(gcloud run services describe router-wpp --region us-central1 --format="value(status.url)")

gcloud pubsub subscriptions create wpp-inbound-subscription \
  --topic=wpp-inbound-topic \
  --push-endpoint=${ROUTER_URL} \
  --push-auth-service-account=router-wpp-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

### 6. Configurar Webhook na Meta

1. Obter URL: `gcloud run services describe handler-wpp --region us-central1 --format="value(status.url)"`
2. Acessar [Meta for Developers](https://developers.facebook.com/)
3. Configurar webhook: `https://HANDLER_URL/webhook/wpp`

## Verificação Rápida

```bash
# Health checks
curl https://handler-wpp-XXXXX-uc.a.run.app/health
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" https://router-wpp-XXXXX-uc.a.run.app/health

# Logs
gcloud run services logs tail handler-wpp --region us-central1
gcloud run services logs tail router-wpp --region us-central1
```

## Checklist de Configuração

- [ ] APIs do GCP habilitadas
- [ ] Tópico Pub/Sub criado
- [ ] Secrets criados (Meta App Secret + Token)
- [ ] Firestore configurado (channel_mappings + tenants)
- [ ] handler-wpp deployado
- [ ] router-wpp deployado
- [ ] Subscription Pub/Sub configurada
- [ ] Webhook configurado na Meta
- [ ] Permissões IAM configuradas

## Próximos Passos

1. Leia [DEPLOY.md](DEPLOY.md) para configuração detalhada
2. Leia [USAGE.md](USAGE.md) para entender o funcionamento
3. Leia [DEVELOPMENT.md](DEVELOPMENT.md) para desenvolvimento

## Troubleshooting Rápido

### Erro 401 no webhook
→ Verifique se o Meta App Secret está correto

### Mensagens não processadas
→ Verifique subscription do Pub/Sub e logs do router-wpp

### Erro no Dialogflow
→ Verifique DIALOGFLOW_AGENT_ID e permissões IAM

### Erro ao enviar resposta
→ Verifique token no Secret Manager e phone_number_id

