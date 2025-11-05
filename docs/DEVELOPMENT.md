# Guia de Desenvolvimento

Este documento fornece informações para desenvolvedores que desejam contribuir ou modificar o projeto.

## Estrutura do Código

### handler-wpp/main.py

Serviço FastAPI que:
- Recebe webhooks da Meta via `POST /webhook/wpp`
- Valida assinatura usando SHA-256 HMAC
- Publica mensagens no Pub/Sub
- Implementa handshake via `GET /webhook/wpp`

**Principais funções:**
- `_get_meta_app_secret()`: Busca segredo do Secret Manager
- `_verify_signature()`: Valida assinatura X-Hub-Signature-256
- `webhook_handler()`: Processa webhooks POST
- `webhook_verification()`: Processa verificação GET

### router-wpp/main.py

Serviço FastAPI que:
- Recebe push notifications do Pub/Sub via `POST /`
- Parseia payload da Meta
- Executa lookups no Firestore
- Chama lógica de negócio via `common_logic`
- Envia respostas via Meta Graph API

**Principais funções:**
- `_parse_meta_payload()`: Extrai dados do payload Meta
- `_get_secret_value()`: Busca segredos do Secret Manager
- `_send_whatsapp_message()`: Envia mensagem via Meta Graph API
- `pubsub_handler()`: Processa mensagens Pub/Sub

### common_logic/business_router.py

Módulo compartilhado que:
- Implementa lógica de roteamento de negócio
- Consulta Firestore para dados de contato e configurações
- Determina funnel_id baseado em contact_status
- Chama Dialogflow CX com parâmetros de contexto
- Retorna resposta de texto

**Principais funções:**
- `execute_business_routing()`: Função principal de roteamento
- `_get_firestore_client()`: Cliente Firestore singleton
- `_get_dialogflow_client()`: Cliente Dialogflow CX singleton

## Ambiente de Desenvolvimento Local

### Pré-requisitos

```bash
# Python 3.10+
python --version

# Instalar dependências
pip install -r handler-wpp/requirements.txt
pip install -r router-wpp/requirements.txt
pip install -r common_logic/requirements.txt
```

### Configurar Application Default Credentials

```bash
# Autenticar no GCP
gcloud auth application-default login

# Ou exportar variáveis de ambiente
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
```

### Variáveis de Ambiente

Crie um arquivo `.env` ou exporte as variáveis:

```bash
export GCP_PROJECT="your-project-id"
export META_APP_SECRET_NAME="meta-app-secret"
export WPP_INBOUND_TOPIC="wpp-inbound-topic"
export DIALOGFLOW_LOCATION="us-central1"
export DIALOGFLOW_AGENT_ID="your-agent-id"
export WHATSAPP_API_VERSION="v19.0"
```

### Executar Localmente

#### handler-wpp

```bash
cd handler-wpp
uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

#### router-wpp

```bash
# Do diretório raiz
cd router-wpp
# Adicionar common_logic ao PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:$(pwd)/.."
uvicorn main:app --host 0.0.0.0 --port 8081 --reload
```

### Testar Localmente

#### Testar handler-wpp

```bash
# Health check
curl http://localhost:8080/health

# Verificação de webhook
curl "http://localhost:8080/webhook/wpp?hub.mode=subscribe&hub.challenge=test123"

# Webhook POST (requer assinatura válida)
# Use um cliente HTTP como Postman ou crie um script Python para testar
```

#### Testar router-wpp

```bash
# Health check
curl http://localhost:8081/health

# Simular mensagem Pub/Sub
# Use o script de teste abaixo
```

## Scripts de Teste

### Testar handler-wpp com Mensagem Real

```python
# test_handler.py
import requests
import hmac
import hashlib
import json

META_APP_SECRET = "your-secret"
URL = "http://localhost:8080/webhook/wpp"

# Payload de exemplo da Meta
payload = {
    "object": "whatsapp_business_account",
    "entry": [{
        "id": "123456789",
        "changes": [{
            "value": {
                "messaging_product": "whatsapp",
                "metadata": {
                    "phone_number_id": "987654321"
                },
                "messages": [{
                    "from": "5511999999999",
                    "id": "msg_123",
                    "timestamp": "1234567890",
                    "text": {
                        "body": "Olá, teste"
                    },
                    "type": "text"
                }]
            }
        }]
    }]
}

# Calcular assinatura
payload_bytes = json.dumps(payload).encode('utf-8')
signature = hmac.new(
    META_APP_SECRET.encode('utf-8'),
    payload_bytes,
    hashlib.sha256
).hexdigest()

# Enviar requisição
response = requests.post(
    URL,
    json=payload,
    headers={
        "X-Hub-Signature-256": f"sha256={signature}",
        "Content-Type": "application/json"
    }
)

print(f"Status: {response.status_code}")
print(f"Response: {response.text}")
```

### Testar router-wpp com Mensagem Pub/Sub

```python
# test_router.py
import requests
import base64
import json

URL = "http://localhost:8081/"

# Payload da Meta
meta_payload = {
    "object": "whatsapp_business_account",
    "entry": [{
        "id": "123456789",
        "changes": [{
            "value": {
                "messaging_product": "whatsapp",
                "metadata": {
                    "phone_number_id": "987654321"
                },
                "messages": [{
                    "from": "5511999999999",
                    "id": "msg_123",
                    "timestamp": "1234567890",
                    "text": {
                        "body": "Olá, teste"
                    },
                    "type": "text"
                }]
            }
        }]
    }]
}

# Simular formato Pub/Sub
pubsub_message = {
    "message": {
        "data": base64.b64encode(json.dumps(meta_payload).encode('utf-8')).decode('utf-8'),
        "messageId": "test_message_123",
        "publishTime": "2024-01-01T00:00:00Z"
    }
}

response = requests.post(URL, json=pubsub_message)
print(f"Status: {response.status_code}")
print(f"Response: {response.text}")
```

## Debugging

### Logs Locais

Os serviços usam `logging` padrão do Python. Configure o nível:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Debug no VS Code

Crie `.vscode/launch.json`:

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Python: handler-wpp",
      "type": "python",
      "request": "launch",
      "program": "${workspaceFolder}/handler-wpp/main.py",
      "env": {
        "GCP_PROJECT": "your-project-id",
        "META_APP_SECRET_NAME": "meta-app-secret",
        "WPP_INBOUND_TOPIC": "wpp-inbound-topic"
      },
      "console": "integratedTerminal"
    }
  ]
}
```

### Debug no Cloud Run

Use Cloud Logging para ver logs em tempo real:

```bash
gcloud run services logs tail handler-wpp --region us-central1
```

## Testes Unitários

### Estrutura de Testes

```
tests/
├── test_handler_wpp.py
├── test_router_wpp.py
└── test_common_logic.py
```

### Exemplo de Teste

```python
# tests/test_handler_wpp.py
import pytest
from fastapi.testclient import TestClient
from handler_wpp.main import app

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}

def test_webhook_verification():
    response = client.get(
        "/webhook/wpp",
        params={
            "hub.mode": "subscribe",
            "hub.challenge": "test123",
            "hub.verify_token": "token"
        }
    )
    assert response.status_code == 200
    assert response.text == "test123"
```

## Padrões de Código

### Formatação

Use `black` para formatação:

```bash
pip install black
black handler-wpp/main.py
black router-wpp/main.py
black common_logic/business_router.py
```

### Linting

Use `pylint` ou `flake8`:

```bash
pip install pylint
pylint handler-wpp/main.py
```

### Type Hints

Sempre use type hints:

```python
def process_message(message: str) -> Optional[str]:
    ...
```

## Contribuindo

### Processo

1. Criar branch a partir de `main`
2. Fazer alterações
3. Adicionar testes
4. Verificar linting e formatação
5. Criar Pull Request
6. Revisão e merge

### Checklist

- [ ] Código segue padrões do projeto
- [ ] Testes passam
- [ ] Documentação atualizada
- [ ] Logs adequados
- [ ] Tratamento de erros
- [ ] Type hints

## Estrutura de Dados

### Payload Meta (Entrada)

```json
{
  "object": "whatsapp_business_account",
  "entry": [{
    "id": "WABA_ID",
    "changes": [{
      "value": {
        "messaging_product": "whatsapp",
        "metadata": {
          "phone_number_id": "PHONE_NUMBER_ID",
          "display_phone_number": "..."
        },
        "messages": [{
          "from": "USER_PHONE_NUMBER",
          "id": "MESSAGE_ID",
          "timestamp": "...",
          "text": {
            "body": "MESSAGE_TEXT"
          },
          "type": "text"
        }]
      }
    }]
  }]
}
```

### Parâmetros de Sessão Dialogflow

```python
{
    "tenant_id": "tenant_123",
    "channel_id": "123456789",
    "user_id": "5511999999999",
    "playbook_name": "core_bdr",
    "playbook_config": {...},  # JSON string
    "contact_status": "bdr_inbound",
    "contact_score": 0,
    "contact_context_score": "Lead inbound (BDR Padrão)"
}
```

## Recursos Adicionais

### Documentação da API Meta

- [WhatsApp Business API](https://developers.facebook.com/docs/whatsapp)
- [Webhooks](https://developers.facebook.com/docs/graph-api/webhooks)
- [Sending Messages](https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-messages)

### Documentação GCP

- [Cloud Run](https://cloud.google.com/run/docs)
- [Pub/Sub](https://cloud.google.com/pubsub/docs)
- [Secret Manager](https://cloud.google.com/secret-manager/docs)
- [Firestore](https://cloud.google.com/firestore/docs)
- [Dialogflow CX](https://cloud.google.com/dialogflow/cx/docs)

### Documentação FastAPI

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Testing](https://fastapi.tiangolo.com/tutorial/testing/)

## Perguntas Frequentes

### Como adicionar um novo campo ao contexto do Dialogflow?

Modifique `common_logic/business_router.py` na função `execute_business_routing()` para adicionar o campo ao dicionário `session_params`.

### Como processar diferentes tipos de mensagens (imagem, áudio, etc.)?

Modifique `router-wpp/main.py` na função `_parse_meta_payload()` para extrair diferentes tipos de mensagens.

### Como adicionar retry logic?

Use bibliotecas como `tenacity` ou implemente retry manualmente nos pontos críticos.

### Como monitorar performance?

Use Cloud Monitoring para criar dashboards e alertas baseados nas métricas do Cloud Run.

