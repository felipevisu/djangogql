import graphene

from . import fields  # noqa
from .context import Context

__all__ = ["Context"]


class ResolveInfo(graphene.ResolveInfo):
    context: Context
