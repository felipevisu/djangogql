import graphene

from .context import Context


class ResolveInfo(graphene.ResolveInfo):
    context: Context
