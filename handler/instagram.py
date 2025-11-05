"""
Handler para Instagram.
Instagram usa a mesma API Meta que WhatsApp, então compartilha o MetaHandler.
"""

from .meta import MetaHandler

# Instagram usa a mesma API Meta, então reutiliza MetaHandler
InstagramHandler = MetaHandler

