"""
Router para Instagram.
Instagram usa a mesma API Meta que WhatsApp, então compartilha o MetaRouter.
"""

from .meta import MetaRouter

# Instagram usa a mesma API Meta, então reutiliza MetaRouter
InstagramRouter = MetaRouter

