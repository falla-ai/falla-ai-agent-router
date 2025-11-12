"""
Módulo de lógica de negócio compartilhada para o sistema de roteamento WhatsApp.
"""

from .business_router import (
    execute_business_routing,
    save_message_and_update_conversation,
)

__all__ = [
    'execute_business_routing',
    'save_message_and_update_conversation',
]


