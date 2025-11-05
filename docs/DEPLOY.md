# Manual de Deploy

Este documento fornece instruções detalhadas para fazer o deploy dos serviços no Google Cloud Run.

## Pré-requisitos

Antes de iniciar o deploy, certifique-se de ter:

1. **gcloud CLI instalado e configurado**
   ```bash
   gcloud --version
   gcloud auth login
   gcloud config set project YOUR_PROJECT_ID
   ```

2. **Habilitar APIs necessárias**
   ```bash
   gcloud services enable \
     cloudbuild.googleapis.com \
     run.googleapis.com \
     pubsub.googleapis.com \
     secretmanager.googleapis.com \
     dialogflow.googleapis.com \
     firestore.googleapis.com
   ```

3. **Configurar billing no projeto GCP**

## Configuração Inicial

### 1. Criar Tópico Pub/Sub

```bash
gcloud pubsub topics create wpp-inbound-topic
```

### 2. Criar Segredos no Secret Manager

#### Meta App Secret
```bash
echo -n "YOUR_META_APP_SECRET" | gcloud secrets create meta-app-secret \
  --data-file=- \
  --replication-policy="automatic"
```

#### Tokens de Acesso da Meta (um para cada canal)
```bash
# Exemplo para um canal
echo -n "YOUR_META_ACCESS_TOKEN" | gcloud secrets create meta-token-channel-123 \
  --data-file=- \
  --replication-policy="automatic"
```

### 3. Configurar Firestore

#### Criar coleção channel_mappings
```bash
# Use o console do Firestore ou a CLI
# Exemplo de documento:
# channel_mappings/{channel_id}
#   tenant_id: "tenant_123"
#   credential_secret_name: "meta-token-channel-123"
```

#### Criar coleção tenants
```bash
# Exemplo de documento:
# tenants/{tenant_id}
#   playbook_configs: {
#     "core_bdr": { ... },
#     "core_sdr": { ... }
#   }
```

## Deploy do handler-wpp

### 1. Build da Imagem Docker

```bash
cd handler-wpp
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/handler-wpp
```

Ou usando Docker localmente:

```bash
docker build -t gcr.io/YOUR_PROJECT_ID/handler-wpp .
docker push gcr.io/YOUR_PROJECT_ID/handler-wpp
```

### 2. Criar Conta de Serviço

```bash
gcloud iam service-accounts create handler-wpp-sa \
  --display-name="Handler WhatsApp Service Account"
```

### 3. Atribuir Permissões

```bash
PROJECT_ID=$(gcloud config get-value project)
SERVICE_ACCOUNT="handler-wpp-sa@${PROJECT_ID}.iam.gserviceaccount.com"

# Permissão para publicar no Pub/Sub
gcloud pubsub topics add-iam-policy-binding wpp-inbound-topic \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/pubsub.publisher"

# Permissão para acessar Secret Manager
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/secretmanager.secretAccessor"
```

### 4. Deploy no Cloud Run

```bash
gcloud run deploy handler-wpp \
  --image gcr.io/YOUR_PROJECT_ID/handler-wpp \
  --platform managed \
  --region us-central1 \
  --service-account handler-wpp-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --set-env-vars="GCP_PROJECT=YOUR_PROJECT_ID,META_APP_SECRET_NAME=meta-app-secret,WPP_INBOUND_TOPIC=wpp-inbound-topic" \
  --allow-unauthenticated \
  --port 8080
```

### 5. Obter URL do Serviço

```bash
HANDLER_URL=$(gcloud run services describe handler-wpp \
  --region us-central1 \
  --format="value(status.url)")

echo "Handler URL: ${HANDLER_URL}"
```

### 6. Configurar Webhook na Meta

1. Acesse o [Meta for Developers](https://developers.facebook.com/)
2. Vá para seu App > WhatsApp > Configuration
3. Configure o Webhook URL: `https://${HANDLER_URL}/webhook/wpp`
4. Configure o Verify Token (opcional, mas recomendado)
5. Salve as configurações

## Deploy do router-wpp

### 1. Build da Imagem Docker

**Importante:** O build deve ser feito do diretório raiz do projeto para incluir o módulo `common_logic`.

```bash
cd /path/to/falla-ai-agent-router
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/router-wpp \
  --config=router-wpp/cloudbuild.yaml
```

Ou criar um `cloudbuild.yaml` para o router-wpp:

```yaml
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-f', 'router-wpp/Dockerfile', '-t', 'gcr.io/YOUR_PROJECT_ID/router-wpp', '.']
images:
  - 'gcr.io/YOUR_PROJECT_ID/router-wpp'
```

Ou usar Docker localmente:

```bash
# Do diretório raiz do projeto
docker build -f router-wpp/Dockerfile -t gcr.io/YOUR_PROJECT_ID/router-wpp .
docker push gcr.io/YOUR_PROJECT_ID/router-wpp
```

### 2. Criar Conta de Serviço

```bash
gcloud iam service-accounts create router-wpp-sa \
  --display-name="Router WhatsApp Service Account"
```

### 3. Atribuir Permissões

```bash
PROJECT_ID=$(gcloud config get-value project)
SERVICE_ACCOUNT="router-wpp-sa@${PROJECT_ID}.iam.gserviceaccount.com"

# Permissão para acessar Firestore
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/datastore.user"

# Permissão para Dialogflow
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/dialogflow.apiClient"

# Permissão para acessar Secret Manager
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/secretmanager.secretAccessor"

# Permissão para receber mensagens do Pub/Sub
gcloud pubsub topics add-iam-policy-binding wpp-inbound-topic \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/pubsub.subscriber"
```

### 4. Configurar Push Subscription do Pub/Sub

```bash
PROJECT_ID=$(gcloud config get-value project)
ROUTER_URL="https://router-wpp-XXXXX-uc.a.run.app"  # Substitua pela URL real

gcloud pubsub subscriptions create wpp-inbound-subscription \
  --topic=wpp-inbound-topic \
  --push-endpoint=${ROUTER_URL} \
  --push-auth-service-account=router-wpp-sa@${PROJECT_ID}.iam.gserviceaccount.com
```

### 5. Deploy no Cloud Run

```bash
gcloud run deploy router-wpp \
  --image gcr.io/YOUR_PROJECT_ID/router-wpp \
  --platform managed \
  --region us-central1 \
  --service-account router-wpp-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --set-env-vars="GCP_PROJECT=YOUR_PROJECT_ID,DIALOGFLOW_LOCATION=us-central1,DIALOGFLOW_AGENT_ID=YOUR_AGENT_ID,WHATSAPP_API_VERSION=v19.0" \
  --no-allow-unauthenticated \
  --port 8080 \
  --min-instances 0 \
  --max-instances 10
```

### 6. Atualizar Subscription do Pub/Sub com URL Real

Após o deploy, obtenha a URL real e atualize a subscription:

```bash
ROUTER_URL=$(gcloud run services describe router-wpp \
  --region us-central1 \
  --format="value(status.url)")

gcloud pubsub subscriptions update wpp-inbound-subscription \
  --push-endpoint=${ROUTER_URL}
```

## Verificação do Deploy

### 1. Verificar Health Check

```bash
# Handler
curl https://handler-wpp-XXXXX-uc.a.run.app/health

# Router
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  https://router-wpp-XXXXX-uc.a.run.app/health
```

### 2. Verificar Logs

```bash
# Logs do handler-wpp
gcloud run services logs read handler-wpp --region us-central1

# Logs do router-wpp
gcloud run services logs read router-wpp --region us-central1
```

### 3. Testar Webhook Manualmente

```bash
# Testar verificação (GET)
curl "https://handler-wpp-XXXXX-uc.a.run.app/webhook/wpp?hub.mode=subscribe&hub.challenge=test123&hub.verify_token=YOUR_TOKEN"

# Testar webhook (POST) - requer assinatura válida
curl -X POST https://handler-wpp-XXXXX-uc.a.run.app/webhook/wpp \
  -H "Content-Type: application/json" \
  -H "X-Hub-Signature-256: sha256=..." \
  -d '{"entry":[...]}'
```

## Monitoramento

### 1. Configurar Alertas

```bash
# Criar alerta para erros no handler-wpp
gcloud alpha monitoring policies create \
  --notification-channels=CHANNEL_ID \
  --display-name="Handler WPP Errors" \
  --condition-display-name="Error Rate > 5%" \
  --condition-threshold-value=0.05 \
  --condition-threshold-duration=300s
```

### 2. Visualizar Métricas

- Acesse o [Cloud Console](https://console.cloud.google.com/)
- Vá para Cloud Run > handler-wpp ou router-wpp
- Visualize métricas de requisições, latência, erros, etc.

## Troubleshooting

### Problema: Erro 401 ao receber webhook
**Solução:** Verifique se o Meta App Secret está correto no Secret Manager e se a assinatura está sendo calculada corretamente.

### Problema: Mensagens não chegam no router-wpp
**Solução:** 
1. Verifique se a subscription do Pub/Sub está configurada corretamente
2. Verifique se a URL do push endpoint está correta
3. Verifique os logs do Pub/Sub

### Problema: Erro ao acessar Firestore
**Solução:** Verifique se a conta de serviço tem a role `roles/datastore.user`.

### Problema: Erro ao chamar Dialogflow
**Solução:** 
1. Verifique se o DIALOGFLOW_AGENT_ID está correto
2. Verifique se a conta de serviço tem a role `roles/dialogflow.apiClient`
3. Verifique se o agente existe e está ativo

## Atualização dos Serviços

Para atualizar um serviço após mudanças no código:

```bash
# Rebuild e redeploy do handler-wpp
cd handler-wpp
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/handler-wpp
gcloud run deploy handler-wpp --image gcr.io/YOUR_PROJECT_ID/handler-wpp --region us-central1

# Rebuild e redeploy do router-wpp (do diretório raiz)
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/router-wpp --config=router-wpp/cloudbuild.yaml
gcloud run deploy router-wpp --image gcr.io/YOUR_PROJECT_ID/router-wpp --region us-central1
```

## Rollback

Para fazer rollback para uma versão anterior:

```bash
# Listar revisões
gcloud run revisions list --service=handler-wpp --region us-central1

# Fazer rollback
gcloud run services update-traffic handler-wpp \
  --to-revisions=REVISION_NAME=100 \
  --region us-central1
```

## Limpeza

Para remover todos os recursos:

```bash
# Deletar serviços Cloud Run
gcloud run services delete handler-wpp --region us-central1
gcloud run services delete router-wpp --region us-central1

# Deletar subscription
gcloud pubsub subscriptions delete wpp-inbound-subscription

# Deletar tópico (opcional, cuidado!)
gcloud pubsub topics delete wpp-inbound-topic

# Deletar contas de serviço
gcloud iam service-accounts delete handler-wpp-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com
gcloud iam service-accounts delete router-wpp-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

