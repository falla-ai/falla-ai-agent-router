"""
Serviço unificado de roteamento.
Orquestrador que registra endpoints e delega para handlers e routers específicos por plataforma.
"""

import os
import logging
from typing import Dict

from fastapi import FastAPI, Request, Response, HTTPException, Query
from fastapi.responses import JSONResponse

from handler.meta import MetaHandler
from handler.linkedin import LinkedInHandler
from handler.instagram import InstagramHandler
from router.meta import MetaRouter
from router.linkedin import LinkedInRouter
from router.instagram import InstagramRouter
from common_logic.business_router import execute_business_routing

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Inicialização do FastAPI
app = FastAPI(title="Router Service - Unified Handler & Router")

# Configurações
PROJECT_ID = os.environ.get("GCP_PROJECT")

# Registro de handlers e routers por plataforma
HANDLERS: Dict[str, object] = {
    "whatsapp": MetaHandler(),
    "instagram": InstagramHandler(),  # Instagram usa Meta API
    "linkedin": LinkedInHandler(),  # LinkedIn (quando implementado)
    "meta": MetaHandler(),  # Alias genérico
}

ROUTERS: Dict[str, object] = {
    "whatsapp": MetaRouter(),
    "instagram": InstagramRouter(),  # Instagram usa Meta API
    "linkedin": LinkedInRouter(),  # LinkedIn (quando implementado)
    "meta": MetaRouter(),  # Alias genérico
}


# ========== ENDPOINTS HANDLER (WEBHOOK) ==========

@app.get("/webhook/{platform}")
async def webhook_verification(
    platform: str,
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_challenge: str = Query(..., alias="hub.challenge"),
    hub_verify_token: str = Query(..., alias="hub.verify_token")
):
    """
    Endpoint GET para verificação do webhook (handshake).
    
    Args:
        platform: Plataforma (ex: whatsapp, instagram, linkedin)
        hub_mode: Deve ser "subscribe"
        hub_challenge: Challenge string que deve ser retornada
        hub_verify_token: Token de verificação (opcional)
        
    Returns:
        O hub.challenge como texto plano (HTTP 200)
    """
    logger.info(f"Handshake de verificação recebido: platform={platform}, mode={hub_mode}, challenge={hub_challenge}")
    return Response(content=hub_challenge, media_type="text/plain")


@app.post("/webhook/{platform}")
async def webhook_handler(platform: str, request: Request):
    """
    Endpoint POST para receber webhooks.
    
    Valida a assinatura, publica no Pub/Sub com metadata da plataforma e retorna 200 OK imediatamente.
    
    Args:
        platform: Plataforma (ex: whatsapp, instagram, linkedin)
        
    Returns:
        HTTP 200 OK se sucesso
        HTTP 401 Unauthorized se assinatura inválida
        HTTP 404 Not Found se plataforma não suportada
        HTTP 500 Internal Server Error se erro interno
    """
    try:
        # Verificar se a plataforma é suportada
        handler = HANDLERS.get(platform.lower())
        if not handler:
            logger.error(f"Plataforma não suportada: {platform}")
            raise HTTPException(status_code=404, detail=f"Platform not supported: {platform}")
        
        # Ler o corpo bruto da requisição
        body = await request.body()
        
        # Verificar assinatura
        signature = request.headers.get("X-Hub-Signature-256")
        
        if not signature:
            logger.error("Requisição sem header X-Hub-Signature-256")
            raise HTTPException(status_code=401, detail="Assinatura não fornecida")
        
        # Buscar segredo e validar assinatura
        try:
            secret = handler.get_meta_app_secret()
        except Exception as e:
            logger.error(f"Erro ao buscar segredo: {e}")
            raise HTTPException(status_code=500, detail="Erro interno ao buscar segredo")
        
        # Validar assinatura
        if not handler.verify_signature(body, signature, secret):
            logger.error("Assinatura inválida - requisição rejeitada")
            raise HTTPException(status_code=401, detail="Assinatura inválida")
        
        logger.info(f"Assinatura validada com sucesso para platform={platform}")
        
        # Publicar no Pub/Sub com metadata da plataforma
        try:
            message_id = handler.publish_to_pubsub(body, platform)
        except Exception as e:
            logger.error(f"Erro ao publicar no Pub/Sub: {e}")
            return JSONResponse(
                content={"status": "enqueued", "error": str(e)},
                status_code=200
            )
        
        # Retornar 200 OK imediatamente após enfileirar
        return JSONResponse(
            content={"status": "ok", "message_id": message_id, "platform": platform},
            status_code=200
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro inesperado ao processar webhook: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno ao processar webhook")


# ========== ENDPOINT ROUTER (PUB/SUB PUSH) ==========

@app.post("/pubsub")
async def pubsub_handler(request: Request):
    """
    Endpoint POST para receber notificações push do Pub/Sub.
    
    Processa a mensagem, faz lookups, chama a lógica de negócio e envia resposta.
    
    Returns:
        HTTP 200 OK se processado com sucesso (mesmo com erros internos)
    """
    try:
        # Desempacotar mensagem do Pub/Sub
        request_json = await request.json()
        
        if 'message' not in request_json:
            logger.error("Payload Pub/Sub inválido, sem campo 'message'")
            return JSONResponse(content={"status": "error", "message": "Invalid payload"}, status_code=200)
        
        message = request_json['message']
        
        # Extrair metadata da plataforma (se disponível)
        attributes = message.get('attributes', {})
        platform = attributes.get('platform', 'whatsapp').lower()  # Default para whatsapp
        
        # Verificar se a plataforma é suportada
        router = ROUTERS.get(platform)
        if not router:
            logger.error(f"Plataforma não suportada no router: {platform}")
            return JSONResponse(
                content={"status": "error", "message": f"Platform not supported: {platform}"},
                status_code=200
            )
        
        # Parsear payload usando o router específico da plataforma
        parsed_data = router.parse_payload(request_json)
        if not parsed_data:
            logger.error("Não foi possível parsear payload")
            return JSONResponse(content={"status": "error", "message": "Invalid payload"}, status_code=200)
        
        channel_id = parsed_data["channel_id"]
        user_id = parsed_data["user_id"]
        message_text = parsed_data["message_text"]
        phone_number_id = parsed_data.get("phone_number_id")
        
        # Lookup 1: Validação de Canal (Firestore)
        channel_mapping = router.get_channel_mapping(channel_id)
        if not channel_mapping:
            logger.error(f"Canal não provisionado: channel_id={channel_id}")
            return JSONResponse(
                content={"status": "error", "message": f"Channel not provisioned: {channel_id}"},
                status_code=200
            )
        
        tenant_id = channel_mapping["tenant_id"]
        credential_secret_name = channel_mapping["credential_secret_name"]
        
        logger.info(f"Lookup 1 concluído: tenant_id={tenant_id}, channel_id={channel_id}, platform={platform}")
        
        # Chamar lógica de negócio compartilhada
        try:
            response_text = execute_business_routing(
                tenant_id=tenant_id,
                user_id=user_id,
                channel_id=channel_id,
                message_text=message_text
            )
        except Exception as e:
            logger.error(f"Erro ao executar roteamento de negócio: {e}", exc_info=True)
            response_text = None
        
        # Lógica de Saída (Outbound)
        if response_text:
            try:
                # Buscar token do Secret Manager
                access_token = router.get_secret_value(credential_secret_name)
                
                # Verificar se phone_number_id está disponível
                if not phone_number_id:
                    logger.error("phone_number_id não encontrado no payload")
                else:
                    # Enviar resposta usando o router específico da plataforma
                    success = router.send_message(
                        phone_number=user_id,
                        message_text=response_text,
                        phone_number_id=phone_number_id,
                        access_token=access_token
                    )
                    
                    if success:
                        logger.info(f"Resposta enviada com sucesso para user_id={user_id}")
                    else:
                        logger.error(f"Falha ao enviar resposta para user_id={user_id}")
                        
            except Exception as e:
                logger.error(f"Erro ao enviar resposta: {e}", exc_info=True)
        else:
            logger.info(f"Nenhuma resposta gerada para user_id={user_id}")
        
        # Sempre retornar 200 OK para confirmar a mensagem Pub/Sub
        return JSONResponse(
            content={"status": "processed", "platform": platform},
            status_code=200
        )
        
    except Exception as e:
        logger.error(f"Erro inesperado ao processar mensagem Pub/Sub: {e}", exc_info=True)
        return JSONResponse(
            content={"status": "error", "message": str(e)},
            status_code=200
        )


# ========== ENDPOINT HEALTH CHECK ==========

@app.get("/health")
async def health_check():
    """Endpoint de health check."""
    return {"status": "healthy", "service": "unified-router"}


# ========== MAIN ==========

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)

