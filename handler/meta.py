"""
Handler para plataformas Meta (WhatsApp, Instagram).
Implementa validação de assinatura e publicação no Pub/Sub.
"""

import os
import hmac
import hashlib
import logging
from typing import Optional

from google.cloud import pubsub_v1
from google.cloud import secretmanager

logger = logging.getLogger(__name__)

# Configurações
PROJECT_ID = os.environ.get("GCP_PROJECT")
META_APP_SECRET_NAME = os.environ.get("META_APP_SECRET_NAME", "meta-app-secret")
WPP_INBOUND_TOPIC = os.environ.get("WPP_INBOUND_TOPIC", "wpp-inbound-topic")

# Clientes singleton
_publisher = None
_secret_client = None


def _get_publisher_client():
    """Retorna o cliente Publisher do Pub/Sub (singleton)."""
    global _publisher
    if _publisher is None:
        try:
            _publisher = pubsub_v1.PublisherClient()
            logger.info("Cliente Pub/Sub Publisher inicializado com sucesso")
        except Exception as e:
            logger.error(f"Erro ao inicializar o cliente Pub/Sub: {e}")
            raise
    return _publisher


def _get_secret_client():
    """Retorna o cliente Secret Manager (singleton)."""
    global _secret_client
    if _secret_client is None:
        try:
            _secret_client = secretmanager.SecretManagerServiceClient()
            logger.info("Cliente Secret Manager inicializado com sucesso")
        except Exception as e:
            logger.error(f"Erro ao inicializar o cliente Secret Manager: {e}")
            raise
    return _secret_client


class MetaHandler:
    """Handler para plataformas Meta (WhatsApp, Instagram)."""
    
    @staticmethod
    def get_meta_app_secret() -> str:
        """Busca o Meta App Secret do Secret Manager."""
        try:
            secret_client = _get_secret_client()
            secret_name = f"projects/{PROJECT_ID}/secrets/{META_APP_SECRET_NAME}/versions/latest"
            response = secret_client.access_secret_version(request={"name": secret_name})
            secret_value = response.payload.data.decode("UTF-8")
            logger.info("Meta App Secret recuperado com sucesso")
            return secret_value
        except Exception as e:
            logger.error(f"Erro ao buscar Meta App Secret: {e}")
            raise
    
    @staticmethod
    def verify_signature(payload: bytes, signature: Optional[str], secret: str) -> bool:
        """
        Verifica a assinatura X-Hub-Signature-256 da Meta.
        
        Args:
            payload: Corpo bruto da requisição em bytes
            signature: Valor do header X-Hub-Signature-256 (formato: sha256=...)
            secret: Meta App Secret
            
        Returns:
            True se a assinatura for válida, False caso contrário
        """
        if not signature:
            return False
        
        if signature.startswith("sha256="):
            signature = signature[7:]
        
        try:
            expected_signature = hmac.new(
                secret.encode('utf-8'),
                payload,
                hashlib.sha256
            ).hexdigest()
            return hmac.compare_digest(expected_signature, signature)
        except Exception as e:
            logger.error(f"Erro ao verificar assinatura: {e}")
            return False
    
    @staticmethod
    def publish_to_pubsub(payload: bytes, platform: str) -> str:
        """
        Publica o payload no Pub/Sub com metadata da plataforma.
        
        Args:
            payload: Corpo bruto da requisição em bytes
            platform: Plataforma (ex: whatsapp, instagram)
            
        Returns:
            Message ID da mensagem publicada
            
        Raises:
            Exception: Se não conseguir publicar
        """
        try:
            publisher = _get_publisher_client()
            topic_path = publisher.topic_path(PROJECT_ID, WPP_INBOUND_TOPIC)
            
            # Publicar o corpo JSON bruto com atributos (metadata da plataforma)
            future = publisher.publish(
                topic_path,
                payload,
                platform=platform  # Atributo customizado para o router identificar a plataforma
            )
            message_id = future.result()
            
            logger.info(f"Mensagem publicada no Pub/Sub com sucesso. Message ID: {message_id}, Platform: {platform}")
            return message_id
        except Exception as e:
            logger.error(f"Erro ao publicar no Pub/Sub: {e}")
            raise

