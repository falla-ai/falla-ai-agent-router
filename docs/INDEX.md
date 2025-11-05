# Índice da Documentação

Bem-vindo à documentação do Router WhatsApp. Este índice ajuda você a encontrar rapidamente a informação que precisa.

## Documentação Principal

### 📖 [README.md](../README.md)
Visão geral do projeto, arquitetura e componentes principais.

### 🚀 [QUICKSTART.md](QUICKSTART.md)
Guia rápido de início para colocar o sistema em funcionamento em 5 minutos.

## Guias Detalhados

### 🛠️ [DEPLOY.md](DEPLOY.md)
Manual completo de deploy com instruções passo a passo:
- Configuração inicial do GCP
- Criação de recursos (Pub/Sub, Secrets, Firestore)
- Deploy dos serviços no Cloud Run
- Configuração de permissões IAM
- Verificação e troubleshooting

### 📱 [USAGE.md](USAGE.md)
Manual de uso e configuração:
- Configuração do webhook na Meta
- Estrutura de dados do Firestore
- Fluxo de funcionamento
- Monitoramento e logs
- Troubleshooting comum

### 💻 [DEVELOPMENT.md](DEVELOPMENT.md)
Guia para desenvolvedores:
- Ambiente de desenvolvimento local
- Estrutura do código
- Scripts de teste
- Debugging
- Padrões de código
- Processo de contribuição

## Por Onde Começar?

### Se você é novo no projeto:
1. Comece com [README.md](../README.md) para entender a arquitetura
2. Use [QUICKSTART.md](QUICKSTART.md) para deploy rápido
3. Consulte [DEPLOY.md](DEPLOY.md) para detalhes

### Se você vai fazer deploy:
1. Leia [QUICKSTART.md](QUICKSTART.md) para visão geral
2. Siga [DEPLOY.md](DEPLOY.md) passo a passo
3. Use [USAGE.md](USAGE.md) para configuração e testes

### Se você vai desenvolver:
1. Leia [README.md](../README.md) para contexto
2. Configure ambiente com [DEVELOPMENT.md](DEVELOPMENT.md)
3. Consulte [USAGE.md](USAGE.md) para entender o fluxo

### Se você precisa resolver problemas:
1. Consulte seção de Troubleshooting em [USAGE.md](USAGE.md)
2. Verifique logs e configurações em [DEPLOY.md](DEPLOY.md)
3. Use [DEVELOPMENT.md](DEVELOPMENT.md) para debugging

## Referências Rápidas

### Variáveis de Ambiente

#### handler-wpp
- `GCP_PROJECT`: ID do projeto GCP
- `META_APP_SECRET_NAME`: Nome do segredo (padrão: `meta-app-secret`)
- `WPP_INBOUND_TOPIC`: Nome do tópico Pub/Sub (padrão: `wpp-inbound-topic`)

#### router-wpp
- `GCP_PROJECT`: ID do projeto GCP
- `DIALOGFLOW_LOCATION`: Localização do agente (padrão: `us-central1`)
- `DIALOGFLOW_AGENT_ID`: ID do agente Dialogflow CX
- `WHATSAPP_API_VERSION`: Versão da API Meta (padrão: `v19.0`)

### Comandos Úteis

```bash
# Ver logs
gcloud run services logs tail handler-wpp --region us-central1
gcloud run services logs tail router-wpp --region us-central1

# Health check
curl https://handler-wpp-XXXXX-uc.a.run.app/health

# Atualizar variáveis de ambiente
gcloud run services update handler-wpp --update-env-vars="KEY=VALUE"

# Listar serviços
gcloud run services list --region us-central1
```

### Estrutura Firestore

```
channel_mappings/{channel_id}
  - tenant_id: string
  - credential_secret_name: string

tenants/{tenant_id}
  - playbook_configs: {
      "core_bdr": {...},
      "core_sdr": {...}
    }

tenants/{tenant_id}/contacts/{user_id}
  - contact_status: string
  - contact_score: number
  - contact_context_score: string
```

## Links Úteis

- [Google Cloud Console](https://console.cloud.google.com/)
- [Meta for Developers](https://developers.facebook.com/)
- [Dialogflow CX Documentation](https://cloud.google.com/dialogflow/cx/docs)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)

## Suporte

Para questões ou problemas:
1. Consulte a documentação relevante
2. Verifique logs e métricas
3. Entre em contato com a equipe de desenvolvimento

