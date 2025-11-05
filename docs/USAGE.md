# Manual de Uso

Este documento fornece instruções sobre como usar e configurar os serviços após o deploy.

## Configuração Inicial

### 1. Configurar Webhook na Meta

Após o deploy do `handler-wpp`, você precisa configurar o webhook na plataforma Meta:

1. Acesse [Meta for Developers](https://developers.facebook.com/)
2. Vá para seu App > WhatsApp > Configuration
3. Em "Webhook", configure:
   - **Callback URL**: `https://handler-wpp-XXXXX-uc.a.run.app/webhook/wpp`
   - **Verify Token**: (opcional, mas recomendado para segurança adicional)
4. Clique em "Verify and Save"
5. Selecione os campos de webhook que deseja receber:
   - `messages`
   - `message_status`
   - (outros conforme necessário)

### 2. Configurar Firestore

#### Estrutura de Dados

##### channel_mappings
Mapeia cada canal (WABA ID) para um tenant e token de acesso.

```javascript
// Exemplo de documento
{
  "tenant_id": "tenant_123",
  "credential_secret_name": "meta-token-channel-123"
}
```

**Como criar:**
```bash
# Via gcloud
gcloud firestore documents create \
  channel_mappings/123456789 \
  --data='{"tenant_id":"tenant_123","credential_secret_name":"meta-token-channel-123"}'
```

Ou via console do Firestore ou código Python/Firebase Admin SDK.

##### tenants
Configuração de cada tenant com playbooks.

```javascript
// Estrutura do documento
{
  "playbook_configs": {
    "core_bdr": {
      "agent_id": "agent_123",
      "language": "pt-br",
      // ... outras configurações do playbook
    },
    "core_sdr": {
      "agent_id": "agent_456",
      "language": "pt-br",
      // ... outras configurações do playbook
    }
  }
}
```

**Como criar:**
```javascript
// Exemplo via código
const admin = require('firebase-admin');
const db = admin.firestore();

await db.collection('tenants').doc('tenant_123').set({
  playbook_configs: {
    core_bdr: {
      agent_id: 'agent_123',
      language: 'pt-br'
    },
    core_sdr: {
      agent_id: 'agent_456',
      language: 'pt-br'
    }
  }
});
```

##### contacts (Opcional)
Dados de contatos dos usuários. Se não existir, será criado automaticamente com valores padrão BDR.

```javascript
// Estrutura do documento
{
  "contact_status": "bdr_inbound",
  "contact_score": 0,
  "contact_context_score": "Lead inbound (BDR Padrão)"
}
```

**Valores padrão quando não existe:**
- `contact_status`: `"bdr_inbound"`
- `contact_score`: `0`
- `contact_context_score`: `"Lead inbound (BDR Padrão)"`
- `funnel_id`: `"core_bdr"`

**Regra de roteamento:**
- Se `contact_status` começa com `"sdr_"`, o `funnel_id` será `"core_sdr"`
- Caso contrário, o `funnel_id` será `"core_bdr"`

### 3. Configurar Secret Manager

#### Meta App Secret
Usado para validar assinaturas de webhooks.

```bash
echo -n "YOUR_META_APP_SECRET" | gcloud secrets create meta-app-secret \
  --data-file=- \
  --replication-policy="automatic"
```

**Onde encontrar o App Secret:**
1. Meta for Developers > Seu App > Settings > Basic
2. Em "App Secret", clique em "Show"
3. Copie o valor

#### Tokens de Acesso da Meta
Um token para cada canal (Phone Number ID).

```bash
# Criar segredo para cada canal
echo -n "YOUR_META_ACCESS_TOKEN" | gcloud secrets create meta-token-channel-123 \
  --data-file=- \
  --replication-policy="automatic"
```

**Onde encontrar o Access Token:**
1. Meta for Developers > Seu App > WhatsApp > API Setup
2. Em "Temporary access token" ou crie um token permanente
3. Copie o token

**Importante:** O nome do segredo deve corresponder ao `credential_secret_name` no Firestore `channel_mappings`.

## Fluxo de Funcionamento

### 1. Recebimento de Mensagem

1. Usuário envia mensagem via WhatsApp
2. Meta envia webhook para `handler-wpp`
3. `handler-wpp` valida assinatura
4. Se válida, publica mensagem no Pub/Sub
5. Retorna 200 OK para Meta

### 2. Processamento

1. Pub/Sub envia mensagem para `router-wpp`
2. `router-wpp` parseia payload da Meta
3. Extrai `channel_id`, `user_id`, `message_text`
4. Consulta `channel_mappings` no Firestore
5. Obtém `tenant_id` e `credential_secret_name`

### 3. Roteamento de Negócio

1. Consulta `tenants/{tenant_id}/contacts/{user_id}` no Firestore
2. Determina `funnel_id` baseado em `contact_status`
3. Consulta `tenants/{tenant_id}` para obter `playbook_config`
4. Prepara parâmetros de sessão para Dialogflow
5. Chama Dialogflow CX com `message_text` e parâmetros

### 4. Resposta

1. Dialogflow retorna resposta de texto
2. `router-wpp` busca token do Secret Manager
3. Envia resposta via Meta Graph API
4. Usuário recebe mensagem no WhatsApp

## Configuração de Variáveis de Ambiente

### handler-wpp

```bash
gcloud run services update handler-wpp \
  --update-env-vars="GCP_PROJECT=your-project-id,META_APP_SECRET_NAME=meta-app-secret,WPP_INBOUND_TOPIC=wpp-inbound-topic" \
  --region us-central1
```

### router-wpp

```bash
gcloud run services update router-wpp \
  --update-env-vars="GCP_PROJECT=your-project-id,DIALOGFLOW_LOCATION=us-central1,DIALOGFLOW_AGENT_ID=your-agent-id,WHATSAPP_API_VERSION=v19.0" \
  --region us-central1
```

## Monitoramento e Logs

### Ver Logs em Tempo Real

```bash
# Logs do handler-wpp
gcloud run services logs tail handler-wpp --region us-central1

# Logs do router-wpp
gcloud run services logs tail router-wpp --region us-central1
```

### Buscar Logs Específicos

```bash
# Logs de erros
gcloud logging read "resource.type=cloud_run_revision AND severity>=ERROR" \
  --limit 50 \
  --format json

# Logs de um serviço específico
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=handler-wpp" \
  --limit 50
```

### Métricas no Console

1. Acesse [Cloud Console](https://console.cloud.google.com/)
2. Vá para Cloud Run
3. Selecione o serviço (`handler-wpp` ou `router-wpp`)
4. Visualize:
   - Requisições por segundo
   - Latência
   - Taxa de erros
   - Uso de memória/CPU

## Testes

### Testar Verificação de Webhook

```bash
curl "https://handler-wpp-XXXXX-uc.a.run.app/webhook/wpp?hub.mode=subscribe&hub.challenge=test123&hub.verify_token=YOUR_TOKEN"
```

**Resposta esperada:** `test123` (texto plano)

### Testar Health Check

```bash
# Handler
curl https://handler-wpp-XXXXX-uc.a.run.app/health

# Router (requer autenticação)
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  https://router-wpp-XXXXX-uc.a.run.app/health
```

### Testar Envio de Mensagem Manual

Para testar o fluxo completo, você pode enviar uma mensagem de teste via WhatsApp diretamente para o número configurado na Meta.

## Troubleshooting

### Problema: Webhook não recebe mensagens

**Diagnóstico:**
1. Verifique se o webhook está configurado corretamente na Meta
2. Verifique os logs do `handler-wpp`
3. Verifique se a assinatura está sendo validada corretamente

**Solução:**
```bash
# Verificar logs recentes
gcloud run services logs read handler-wpp --region us-central1 --limit 50
```

### Problema: Mensagens não são processadas

**Diagnóstico:**
1. Verifique se há mensagens no Pub/Sub
2. Verifique se a subscription está configurada corretamente
3. Verifique os logs do `router-wpp`

**Solução:**
```bash
# Verificar mensagens não entregues
gcloud pubsub subscriptions describe wpp-inbound-subscription

# Verificar métricas do Pub/Sub
gcloud pubsub topics describe wpp-inbound-topic
```

### Problema: Erro ao buscar configurações no Firestore

**Diagnóstico:**
1. Verifique se o documento existe no Firestore
2. Verifique se a estrutura está correta
3. Verifique permissões IAM

**Solução:**
```bash
# Verificar documento
gcloud firestore documents get channel_mappings/CHANNEL_ID

# Verificar permissões
gcloud projects get-iam-policy YOUR_PROJECT_ID \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:router-wpp-sa@*"
```

### Problema: Dialogflow não retorna resposta

**Diagnóstico:**
1. Verifique se o `DIALOGFLOW_AGENT_ID` está correto
2. Verifique se o agente está ativo
3. Verifique se os parâmetros de sessão estão corretos
4. Verifique os logs do `router-wpp` para erros do Dialogflow

**Solução:**
```bash
# Verificar agente
gcloud dialogflow cx agents list --location=us-central1

# Verificar logs com foco em Dialogflow
gcloud run services logs read router-wpp --region us-central1 \
  --limit 100 | grep -i dialogflow
```

### Problema: Resposta não é enviada ao usuário

**Diagnóstico:**
1. Verifique se o token está correto no Secret Manager
2. Verifique se o `phone_number_id` está correto
3. Verifique se o formato da mensagem está correto
4. Verifique os logs do `router-wpp` para erros da API Meta

**Solução:**
```bash
# Verificar token
gcloud secrets versions access latest --secret=meta-token-channel-123

# Verificar logs de envio
gcloud run services logs read router-wpp --region us-central1 \
  --limit 100 | grep -i "enviar\|send\|whatsapp"
```

## Boas Práticas

### 1. Monitoramento Proativo

Configure alertas para:
- Taxa de erros > 5%
- Latência > 2 segundos
- Mensagens não processadas no Pub/Sub

### 2. Versionamento

Sempre teste novas versões em um ambiente de staging antes de produção.

### 3. Backup de Configurações

Mantenha backup das configurações do Firestore e Secret Manager.

### 4. Logs Estruturados

Os logs já estão estruturados, mas você pode adicionar mais contexto se necessário.

### 5. Rate Limiting

O Cloud Run já gerencia escalabilidade, mas você pode configurar limites se necessário.

## Escalabilidade

Os serviços são automaticamente escaláveis no Cloud Run:
- **Mínimo de instâncias**: 0 (configurável)
- **Máximo de instâncias**: 10 (configurável)
- **Concorrência**: 80 requisições por instância (padrão)

Para ajustar:

```bash
gcloud run services update handler-wpp \
  --min-instances 1 \
  --max-instances 20 \
  --concurrency 100 \
  --region us-central1
```

## Custos

Os principais custos são:
- **Cloud Run**: Baseado em requisições e tempo de execução
- **Pub/Sub**: Baseado em mensagens
- **Firestore**: Baseado em leituras/escritas
- **Dialogflow CX**: Baseado em sessões/requisições
- **Secret Manager**: Gratuito até certo limite

Consulte a [calculadora de preços do GCP](https://cloud.google.com/products/calculator) para estimativas.

