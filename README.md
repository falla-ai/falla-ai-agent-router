# Arquitetura Router WhatsApp - Documentação

Este projeto implementa uma arquitetura de microserviços para processamento de mensagens WhatsApp usando Google Cloud Platform, Dialogflow CX e Meta Graph API.

## Visão Geral

A arquitetura é composta por três componentes principais:

1. **handler-wpp**: Serviço de ingestão de webhooks da Meta (WhatsApp)
2. **router-wpp**: Serviço de processamento assíncrono e roteamento de mensagens
3. **common_logic**: Módulo compartilhado de lógica de negócio

## Arquitetura

```
┌─────────────┐
│     Meta    │
│  (WhatsApp) │
└──────┬──────┘
       │ Webhook
       ▼
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│ handler-wpp │─────▶│  Pub/Sub     │─────▶│ router-wpp  │
│  (Cloud Run)│      │  (Topic)     │      │  (Cloud Run)│
└─────────────┘      └──────────────┘      └──────┬──────┘
                                                   │
                                                   ▼
                                          ┌──────────────┐
                                          │ common_logic │
                                          │  (Módulo)    │
                                          └──────┬───────┘
                                                 │
                    ┌────────────────────────────┼────────────────────────┐
                    ▼                           ▼                         ▼
            ┌──────────────┐          ┌──────────────┐         ┌──────────────┐
            │  Firestore   │          │  Dialogflow  │         │ Secret Mgr   │
            │  (Database)  │          │      CX      │         │  (Tokens)    │
            └──────────────┘          └──────────────┘         └──────────────┘
```

## Componentes

### handler-wpp
Serviço de ingestão que recebe webhooks da Meta, valida assinaturas e publica mensagens no Pub/Sub.

**Funcionalidades:**
- Validação de assinatura X-Hub-Signature-256
- Handshake de verificação Meta
- Publicação assíncrona no Pub/Sub

### router-wpp
Serviço de processamento que consome mensagens do Pub/Sub, executa lógica de negócio e envia respostas.

**Funcionalidades:**
- Processamento de mensagens Pub/Sub
- Lookup de configurações no Firestore
- Roteamento de negócio via common_logic
- Envio de respostas via Meta Graph API

### common_logic
Módulo compartilhado que implementa a lógica de roteamento de negócio.

**Funcionalidades:**
- Lookup de contatos e configurações no Firestore
- Roteamento baseado em funil (BDR/SDR)
- Integração com Dialogflow CX
- Enriquecimento de contexto

## Estrutura do Projeto

```
falla-ai-agent-router/
├── handler-wpp/              # Serviço de ingestão
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
├── router-wpp/              # Serviço de processamento
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
├── common_logic/            # Módulo compartilhado
│   ├── __init__.py
│   ├── business_router.py
│   └── requirements.txt
└── router-example.py        # Exemplo antigo (legado)
```

## Pré-requisitos

- Google Cloud Platform (GCP) com billing habilitado
- Python 3.10+
- Docker (para build local)
- gcloud CLI instalado e configurado
- Conta Meta com WhatsApp Business API configurada

## Documentação Detalhada

- [📋 Índice da Documentação](docs/INDEX.md) - Navegação completa da documentação
- [🚀 Guia Rápido de Início](docs/QUICKSTART.md) - Deploy rápido em 5 minutos
- [🛠️ Manual de Deploy](docs/DEPLOY.md) - Guia completo de implantação
- [📱 Manual de Uso](docs/USAGE.md) - Guia de uso e configuração
- [💻 Guia de Desenvolvimento](docs/DEVELOPMENT.md) - Informações para desenvolvedores

## Variáveis de Ambiente

### handler-wpp
- `GCP_PROJECT`: ID do projeto GCP
- `META_APP_SECRET_NAME`: Nome do segredo no Secret Manager (padrão: `meta-app-secret`)
- `WPP_INBOUND_TOPIC`: Nome do tópico Pub/Sub (padrão: `wpp-inbound-topic`)
- `PORT`: Porta do servidor (padrão: 8080)

### router-wpp
- `GCP_PROJECT`: ID do projeto GCP
- `DIALOGFLOW_LOCATION`: Localização do agente Dialogflow (padrão: `us-central1`)
- `DIALOGFLOW_AGENT_ID`: ID do agente Dialogflow CX
- `WHATSAPP_API_VERSION`: Versão da API Meta (padrão: `v19.0`)
- `PORT`: Porta do servidor (padrão: 8080)

### common_logic
- `GCP_PROJECT`: ID do projeto GCP
- `DIALOGFLOW_LOCATION`: Localização do agente Dialogflow (padrão: `us-central1`)
- `DIALOGFLOW_AGENT_ID`: ID do agente Dialogflow CX

## Permissões IAM Necessárias

### handler-wpp (Cloud Run Service Account)
- `roles/pubsub.publisher`
- `roles/secretmanager.secretAccessor`

### router-wpp (Cloud Run Service Account)
- `roles/datastore.user`
- `roles/dialogflow.apiClient`
- `roles/secretmanager.secretAccessor`

## Estrutura de Dados Firestore

### channel_mappings
```
channel_mappings/{channel_id}
  - tenant_id: string
  - credential_secret_name: string
```

### tenants
```
tenants/{tenant_id}
  - playbook_configs: {
      "core_bdr": { ... },
      "core_sdr": { ... }
    }
```

### contacts
```
tenants/{tenant_id}/contacts/{user_id}
  - contact_status: string
  - contact_score: number
  - contact_context_score: string
```

## Segurança

- Todas as requisições são validadas usando assinatura SHA-256 HMAC
- Uso de Application Default Credentials (ADC) - sem chaves JSON
- Segredos armazenados no Secret Manager
- Comunicação assíncrona via Pub/Sub

## Suporte

Para questões ou problemas, consulte a documentação detalhada ou entre em contato com a equipe de desenvolvimento.

