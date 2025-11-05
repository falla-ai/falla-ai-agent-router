"""
Router para plataformas Meta (WhatsApp, Instagram).
Implementa parsing de payload e envio de mensagens via Meta Graph API.
"""

import os
import json
import base64
import logging
from typing import Optional, Dict, Any

import requests
from google.cloud import secretmanager
import firebase_admin
from firebase_admin import firestore

logger = logging.getLogger(__name__)

# Configurações
PROJECT_ID = os.environ.get("GCP_PROJECT")
WHATSAPP_API_VERSION = os.environ.get("WHATSAPP_API_VERSION", "v19.0")

# Clientes singleton
_secret_client = None
_db = None


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


def _get_firestore_client():
    """Retorna o cliente Firestore (singleton)."""
    global _db
    if _db is None:
        try:
            if not firebase_admin._apps:
                firebase_admin.initialize_app()
            _db = firestore.client()
            logger.info("Cliente Firestore inicializado com sucesso")
        except Exception as e:
            logger.error(f"Erro ao inicializar o cliente Firestore: {e}")
            raise
    return _db


class MetaRouter:
    """Router para plataformas Meta (WhatsApp, Instagram)."""
    
    @staticmethod
    def get_secret_value(secret_name: str) -> str:
        """Busca um valor do Secret Manager."""
        try:
            secret_client = _get_secret_client()
            secret_path = f"projects/{PROJECT_ID}/secrets/{secret_name}/versions/latest"
            response = secret_client.access_secret_version(request={"name": secret_path})
            secret_value = response.payload.data.decode("UTF-8")
            logger.info(f"Segredo '{secret_name}' recuperado com sucesso")
            return secret_value
        except Exception as e:
            logger.error(f"Erro ao buscar segredo '{secret_name}': {e}")
            raise
    
    @staticmethod
    def parse_payload(pubsub_message: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """
        Parseia o payload do Pub/Sub e extrai informações relevantes.
        
        Args:
            pubsub_message: Mensagem do Pub/Sub (formato JSON completo)
            
        Returns:
            Dicionário com channel_id, user_id, message_text, phone_number_id ou None se não conseguir parsear
        """
        try:
            message = pubsub_message.get('message', {})
            
            if 'data' not in message:
                logger.error("Mensagem Pub/Sub sem campo 'data'")
                return None
            
            # Decodificar payload base64
            payload_bytes = base64.b64decode(message['data'])
            meta_json = json.loads(payload_bytes.decode('utf-8'))
            
            # Parsear estrutura Meta
            entry = meta_json.get("entry", [])
            if not entry:
                logger.error("Payload Meta sem campo 'entry'")
                return None
            
            first_entry = entry[0]
            changes = first_entry.get("changes", [])
            
            if not changes:
                logger.error("Payload Meta sem campo 'changes'")
                return None
            
            first_change = changes[0]
            value = first_change.get("value", {})
            
            # Extrair channel_id (WABA ID ou ID da Página)
            channel_id = first_entry.get("id")
            if not channel_id:
                metadata = value.get("metadata", {})
                channel_id = metadata.get("phone_number_id")
            
            # Extrair mensagens
            messages = value.get("messages", [])
            if not messages:
                logger.warning("Payload Meta sem mensagens (pode ser notificação de status)")
                return None
            
            first_message = messages[0]
            user_id = first_message.get("from")
            
            # Extrair texto da mensagem
            message_text = None
            if first_message.get("type") == "text":
                text_obj = first_message.get("text", {})
                message_text = text_obj.get("body")
            
            # Extrair phone_number_id para envio
            metadata = value.get("metadata", {})
            phone_number_id = metadata.get("phone_number_id")
            
            if not all([channel_id, user_id, message_text]):
                logger.error(f"Payload Meta incompleto: channel_id={channel_id}, user_id={user_id}, message_text={bool(message_text)}")
                return None
            
            result = {
                "channel_id": channel_id,
                "user_id": user_id,
                "message_text": message_text,
                "phone_number_id": phone_number_id
            }
            
            logger.info(f"Payload Meta parseado com sucesso: channel_id={channel_id}, user_id={user_id}")
            return result
            
        except Exception as e:
            logger.error(f"Erro ao parsear payload Meta: {e}", exc_info=True)
            return None
    
    @staticmethod
    def get_channel_mapping(channel_id: str) -> Optional[Dict[str, str]]:
        """
        Busca o mapeamento do canal no Firestore.
        
        Args:
            channel_id: ID do canal (WABA ID ou ID da Página)
            
        Returns:
            Dicionário com tenant_id, credential_secret_name, platform ou None se não encontrado
        """
        try:
            db = _get_firestore_client()
            channel_doc = db.collection("channel_mappings").document(channel_id).get()
            
            if not channel_doc.exists:
                logger.error(f"Canal não provisionado: channel_id={channel_id}")
                return None
            
            channel_data = channel_doc.to_dict()
            tenant_id = channel_data.get("tenant_id")
            credential_secret_name = channel_data.get("credential_secret_name")
            platform = channel_data.get("platform")
            
            if not tenant_id or not credential_secret_name:
                logger.error(f"Dados incompletos no channel_mapping: tenant_id={tenant_id}, credential_secret_name={credential_secret_name}")
                return None
            
            return {
                "tenant_id": tenant_id,
                "credential_secret_name": credential_secret_name,
                "platform": platform
            }
        except Exception as e:
            logger.error(f"Erro ao buscar channel mapping: {e}", exc_info=True)
            return None
    
    @staticmethod
    def send_message(
        phone_number: str,
        message_text: str,
        phone_number_id: str,
        access_token: str
    ) -> bool:
        """
        Envia uma mensagem de texto via Meta Graph API.
        
        Args:
            phone_number: Número de telefone do destinatário (formato E.164)
            message_text: Texto da mensagem
            phone_number_id: ID do número de telefone da Meta (Phone Number ID)
            access_token: Token de acesso da Meta
            
        Returns:
            True se enviado com sucesso, False caso contrário
        """
        url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{phone_number_id}/messages"
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        
        data = {
            "messaging_product": "whatsapp",
            "to": phone_number,
            "text": {"body": message_text},
        }
        
        try:
            response = requests.post(url, headers=headers, json=data, timeout=10)
            response.raise_for_status()
            logger.info(f"Resposta enviada com sucesso para {phone_number}")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Erro ao enviar mensagem para o WhatsApp: {e}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Resposta da API: {e.response.text}")
            return False

