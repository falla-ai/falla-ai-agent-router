"""
Módulo de routers por plataforma.
Cada router implementa parsing de payload e envio de mensagens.
"""

from .meta import MetaRouter
from .linkedin import LinkedInRouter
from .instagram import InstagramRouter

__all__ = ['MetaRouter', 'LinkedInRouter', 'InstagramRouter']

