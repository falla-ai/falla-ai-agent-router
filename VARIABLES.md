# Variáveis de Ambiente Necessárias para Deploy

## Variáveis no Cloud Build (Substitutions)

Estas variáveis devem ser configuradas no Cloud Build Trigger ou como Substitutions.

### Variáveis Obrigatórias

| Variável | Valor | Descrição |
|----------|-------|-----------|
| `_SERVICE_NAME` | `router-service` | Nome do serviço Cloud Run |
| `_REGION` | `us-central1` | Região do Cloud Run |
| `_REPOSITORY` | `cloud-run-source-deploy` | Nome do repositório Artifact Registry |
| `_SERVICE_ACCOUNT` | `router-service-sa@${PROJECT_ID}.iam.gserviceaccount.com` | Service account do Cloud Run |
| `_META_APP_SECRET_NAME` | `meta-app-secret` | Nome do segredo no Secret Manager |
| `_WPP_INBOUND_TOPIC` | `wpp-inbound-topic` | Nome do tópico Pub/Sub |
| `_DIALOGFLOW_LOCATION` | `us-central1` | Localização do agente Dialogflow |
| `_DIALOGFLOW_AGENT_ID` | `7f3455c5-9c67-4c51-a181-dfe3e5a60868` | ID do agente Dialogflow CX |
| `_WHATSAPP_API_VERSION` | `v19.0` | Versão da API Meta Graph |

### Variáveis Automáticas

Estas são fornecidas automaticamente pelo Cloud Build:

- `PROJECT_ID` - ID do projeto GCP
- `SHORT_SHA` - Commit SHA curto (7 caracteres)
- `COMMIT_SHA` - Commit SHA completo
- `BRANCH_NAME` - Nome da branch
- `TAG_NAME` - Tag (se aplicável)

## Como Configurar Variáveis no Cloud Build Trigger

### Via Console do GCP

1. Acesse: https://console.cloud.google.com/cloud-build/triggers
2. Crie um novo trigger ou edite um existente
3. Em "Substitution variables", adicione cada variável acima

### Via gcloud CLI

```bash
gcloud builds triggers create github \
  --repo-name=falla-ai-agent-router \
  --repo-owner=falla-ai \
  --branch-pattern="^main$" \
  --build-config=cloudbuild.yaml \
  --substitutions=_SERVICE_NAME=router-service,_REGION=us-central1,_REPOSITORY=cloud-run-source-deploy,_SERVICE_ACCOUNT=router-service-sa@falla-ai.iam.gserviceaccount.com,_META_APP_SECRET_NAME=meta-app-secret,_WPP_INBOUND_TOPIC=wpp-inbound-topic,_DIALOGFLOW_LOCATION=us-central1,_DIALOGFLOW_AGENT_ID=7f3455c5-9c67-4c51-a181-dfe3e5a60868,_WHATSAPP_API_VERSION=v19.0 \
  --project=falla-ai
```

## Variáveis de Ambiente no Cloud Run

Estas variáveis são configuradas automaticamente pelo cloudbuild.yaml a partir das substitutions:

- `GCP_PROJECT` - ID do projeto (de `PROJECT_ID`)
- `META_APP_SECRET_NAME` - Nome do segredo (de `_META_APP_SECRET_NAME`)
- `WPP_INBOUND_TOPIC` - Tópico Pub/Sub (de `_WPP_INBOUND_TOPIC`)
- `DIALOGFLOW_LOCATION` - Localização Dialogflow (de `_DIALOGFLOW_LOCATION`)
- `DIALOGFLOW_AGENT_ID` - ID do agente (de `_DIALOGFLOW_AGENT_ID`)
- `WHATSAPP_API_VERSION` - Versão API Meta (de `_WHATSAPP_API_VERSION`)
- `PORT` - Porta do servidor (padrão: 8080, configurado no Dockerfile)

## Checklist Antes do Deploy

- [ ] Tópico Pub/Sub `wpp-inbound-topic` criado
- [ ] Secret `meta-app-secret` criado no Secret Manager
- [ ] Service account `router-service-sa` criada com permissões:
  - [ ] `roles/pubsub.publisher`
  - [ ] `roles/datastore.user`
  - [ ] `roles/dialogflow.client`
  - [ ] `roles/secretmanager.secretAccessor`
- [ ] Artifact Registry repository `cloud-run-source-deploy` criado
- [ ] Cloud Build trigger conectado ao repositório GitHub
- [ ] Variáveis de substituição configuradas no trigger

