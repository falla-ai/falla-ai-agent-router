# Guia de Deploy Contínuo (CI/CD) via Cloud Build

Este guia explica como configurar deploy contínuo via Cloud Build conectado ao repositório GitHub.

## Pré-requisitos

1. Repositório GitHub: `falla-ai/falla-ai-agent-router`
2. Cloud Build API habilitada
3. Artifact Registry repository criado
4. Service account configurada

## Dockerfile

O Dockerfile atual está **correto** e funciona perfeitamente com Cloud Build. Não precisa de alterações.

## Variáveis Necessárias no Cloud Build Trigger

### Variáveis Obrigatórias

Configure estas variáveis no Cloud Build Trigger (Substitution variables):

| Variável | Valor | Descrição |
|----------|-------|-----------|
| `_SERVICE_NAME` | `router-service` | Nome do serviço Cloud Run |
| `_REGION` | `us-central1` | Região do Cloud Run |
| `_REPOSITORY` | `cloud-run-source-deploy` | Repositório Artifact Registry |
| `_SERVICE_ACCOUNT` | `router-service-sa@falla-ai.iam.gserviceaccount.com` | Service account |
| `_META_APP_SECRET_NAME` | `meta-app-secret` | Nome do segredo no Secret Manager |
| `_WPP_INBOUND_TOPIC` | `wpp-inbound-topic` | Nome do tópico Pub/Sub |
| `_DIALOGFLOW_LOCATION` | `us-central1` | Localização do agente Dialogflow |
| `_DIALOGFLOW_AGENT_ID` | `7f3455c5-9c67-4c51-a181-dfe3e5a60868` | ID do agente Dialogflow CX |
| `_WHATSAPP_API_VERSION` | `v19.0` | Versão da API Meta Graph |

### Variáveis Automáticas

Estas são fornecidas automaticamente pelo Cloud Build:

- `PROJECT_ID` = `falla-ai` (do projeto GCP)
- `SHORT_SHA` = Commit SHA curto (ex: `a06f3c5`)
- `COMMIT_SHA` = Commit SHA completo
- `BRANCH_NAME` = Nome da branch (ex: `main`)
- `TAG_NAME` = Tag (se aplicável)

## Como Configurar o Trigger no Console GCP

1. Acesse: https://console.cloud.google.com/cloud-build/triggers?project=falla-ai

2. Clique em **"Create Trigger"**

3. Configure:
   - **Name**: `router-service-deploy`
   - **Event**: Push to a branch
   - **Source**: GitHub (falla-ai/falla-ai-agent-router)
   - **Branch**: `^main$` (regex)
   - **Configuration**: Cloud Build configuration file (yaml or json)
   - **Location**: Repository
   - **Cloud Build configuration file location**: `cloudbuild.yaml`

4. Em **"Substitution variables"**, adicione:

```
_SERVICE_NAME=router-service
_REGION=us-central1
_REPOSITORY=cloud-run-source-deploy
_SERVICE_ACCOUNT=router-service-sa@falla-ai.iam.gserviceaccount.com
_META_APP_SECRET_NAME=meta-app-secret
_WPP_INBOUND_TOPIC=wpp-inbound-topic
_DIALOGFLOW_LOCATION=us-central1
_DIALOGFLOW_AGENT_ID=7f3455c5-9c67-4c51-a181-dfe3e5a60868
_WHATSAPP_API_VERSION=v19.0
```

5. Salve o trigger

## Como Configurar via CLI

```bash
gcloud builds triggers create github \
  --repo-name=falla-ai-agent-router \
  --repo-owner=falla-ai \
  --branch-pattern="^main$" \
  --build-config=cloudbuild.yaml \
  --name=router-service-deploy \
  --substitutions=_SERVICE_NAME=router-service,_REGION=us-central1,_REPOSITORY=cloud-run-source-deploy,_SERVICE_ACCOUNT=router-service-sa@falla-ai.iam.gserviceaccount.com,_META_APP_SECRET_NAME=meta-app-secret,_WPP_INBOUND_TOPIC=wpp-inbound-topic,_DIALOGFLOW_LOCATION=us-central1,_DIALOGFLOW_AGENT_ID=7f3455c5-9c67-4c51-a181-dfe3e5a60868,_WHATSAPP_API_VERSION=v19.0 \
  --project=falla-ai
```

## Checklist Antes de Configurar o Trigger

- [x] Tópico Pub/Sub `wpp-inbound-topic` criado
- [x] Secret `meta-app-secret` criado no Secret Manager
- [x] Service account `router-service-sa` criada com permissões
- [x] Artifact Registry `cloud-run-source-deploy` criado
- [ ] Conectar repositório GitHub ao Cloud Build (primeira vez)
- [ ] Criar trigger com as variáveis acima

## Conectar Repositório GitHub (Primeira Vez)

1. Acesse: https://console.cloud.google.com/cloud-build/triggers?project=falla-ai
2. Clique em **"Connect Repository"**
3. Selecione **"GitHub (Cloud Build GitHub App)"**
4. Autorize o acesso ao GitHub
5. Selecione o repositório: `falla-ai/falla-ai-agent-router`
6. Clique em **"Connect"**

## Fluxo de Deploy

1. Push para branch `main` no GitHub
2. Cloud Build detecta o push
3. Executa `cloudbuild.yaml`:
   - Build da imagem Docker
   - Push para Artifact Registry
   - Deploy no Cloud Run com variáveis de ambiente
4. Serviço atualizado automaticamente

## Verificar Deploy

Após o push, verifique:

```bash
# Ver status do build
gcloud builds list --limit=1 --project=falla-ai

# Ver logs do build
gcloud builds log <BUILD_ID> --project=falla-ai

# Verificar serviço
gcloud run services describe router-service --region us-central1 --project=falla-ai
```

