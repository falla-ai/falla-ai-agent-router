"""
Router para LinkedIn.
Implementa parsing de payload e envio de mensagens via LinkedIn API.
TODO: Implementar quando LinkedIn API estiver disponível.
"""

import logging

logger = logging.getLogger(__name__)


class LinkedInRouter:
    """Router para plataforma LinkedIn."""
    
    @staticmethod
    def get_secret_value(secret_name: str) -> str:
        """Busca um valor do Secret Manager."""
        # TODO: Implementar quando LinkedIn API estiver disponível
        raise NotImplementedError("LinkedIn router não implementado ainda")
    
    @staticmethod
    def parse_payload(pubsub_message: dict) -> dict:
        """Parseia o payload do Pub/Sub."""
        # TODO: Implementar quando LinkedIn API estiver disponível
        raise NotImplementedError("LinkedIn router não implementado ainda")
    
    @staticmethod
    def get_channel_mapping(channel_id: str) -> dict:
        """Busca o mapeamento do canal no Firestore."""
        # TODO: Implementar quando LinkedIn API estiver disponível
        raise NotImplementedError("LinkedIn router não implementado ainda")
    
    @staticmethod
    def send_message(
        user_id: str,
        message_text: str,
        channel_id: str,
        access_token: str
    ) -> bool:
        """Envia uma mensagem via LinkedIn API."""
        # TODO: Implementar quando LinkedIn API estiver disponível
        raise NotImplementedError("LinkedIn router não implementado ainda")

