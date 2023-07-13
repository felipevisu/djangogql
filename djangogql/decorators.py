from functools import wraps
from typing import Iterable

from graphene import ResolveInfo

from .exceptions import PermissionDenied
from .permissions import BasePermissionEnum, one_of_permissions_or_auth_filter_required


def context(f):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            info = next(arg for arg in args if isinstance(arg, ResolveInfo))
            return func(info.context, *args, **kwargs)

        return wrapper

    return decorator


def account_passes_test(test_func):
    """Determine if user/app has permission to access to content."""

    def decorator(f):
        @wraps(f)
        @context(f)
        def wrapper(context, *args, **kwargs):
            test_func(context)
            return f(*args, **kwargs)

        return wrapper

    return decorator


def one_of_permissions_required(perms: Iterable[BasePermissionEnum]):
    def check_perms(context):
        if not one_of_permissions_or_auth_filter_required(context, perms):
            raise PermissionDenied()

    return account_passes_test(check_perms)


def account_passes_test_for_attribute(test_func):
    """Determine if user/app has permission to access to content."""

    def decorator(f):
        @wraps(f)
        @context(f)
        def wrapper(context, *args, **kwargs):
            root = args[0]
            test_func(context, root)
            return f(*args, **kwargs)

        return wrapper

    return decorator


def check_attribute_required_permissions():
    def check_perms(context, instance):
        user = context.user
        if not user or not user.is_staff:
            raise PermissionDenied()

    return account_passes_test_for_attribute(check_perms)
