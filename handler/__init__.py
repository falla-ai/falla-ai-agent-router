"""
Módulo de handlers por plataforma.
Cada handler implementa validação de assinatura e publicação no Pub/Sub.
"""

from .meta import MetaHandler
from .linkedin import LinkedInHandler
from .instagram import InstagramHandler

__all__ = ['MetaHandler', 'LinkedInHandler', 'InstagramHandler']

