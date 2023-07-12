from typing import cast

from django.contrib.auth import get_user_model
from django.http import HttpRequest
from django.utils import timezone

from .core.context import Context

User = get_user_model()


def get_context_value(request: HttpRequest) -> Context:
    request = cast(Context, request)
    request.dataloaders = {}
    request.allow_replica = getattr(request, "allow_replica", True)
    request.request_time = timezone.now()
    return request
