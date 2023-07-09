import graphene

from . import fields  # noqa
from .context import PortalContext

__all__ = ["PortalContext"]


class ResolveInfo(graphene.ResolveInfo):
    context: PortalContext
