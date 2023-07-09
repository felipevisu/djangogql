from enum import Enum
from typing import Iterable, List

from django.contrib.auth.models import Permission

from .settings import djangogql_settings


class BasePermissionEnum(Enum):
    @property
    def codename(self):
        return self.value.split(".")[1]



def split_permission_codename(permissions):
    return [permission.split(".")[1] for permission in permissions]


def get_permissions_codename():
    permissions_values = [
        enum.codename
        for permission_enum in djangogql_settings.PERMISSIONS_ENUMS
        for enum in permission_enum
    ]
    return permissions_values


def get_permissions_enum_dict():
    return {
        enum.name: enum
        for permission_enum in djangogql_settings.PERMISSIONS_ENUMS
        for enum in permission_enum
    }


def get_permissions_from_names(names: List[str]):
    """Convert list of permission names - ['MANAGE_ORDERS'] to Permission db objects."""
    permissions = get_permissions_enum_dict()
    return get_permissions([permissions[name].value for name in names])


def get_permission_names(permissions: Iterable["Permission"]):
    """Convert Permissions db objects to list of Permission enums."""
    permission_dict = get_permissions_enum_dict()
    names = set()
    for perm in permissions:
        for _, perm_enum in permission_dict.items():
            if perm.codename == perm_enum.codename:
                names.add(perm_enum.name)
    return names


def get_permissions_enum_list():
    permissions_list = [
        (enum.name, enum.value)
        for permission_enum in djangogql_settings.PERMISSIONS_ENUMS
        for enum in permission_enum
    ]
    return permissions_list


def get_permissions(permissions=None):
    if permissions is None:
        codenames = get_permissions_codename()
    else:
        codenames = split_permission_codename(permissions)
    return get_permissions_from_codenames(codenames)


def get_permissions_from_codenames(permission_codenames: List[str]):
    return (
        Permission.objects.filter(codename__in=permission_codenames)
        .prefetch_related("content_type")
        .order_by("codename")
    )


def is_staff_user(context):
    return context.user.is_staff


class AuthorizationFilters(BasePermissionEnum):
    AUTHENTICATED_STAFF_USER = "authorization_filters.authenticated_staff_user"


AUTHORIZATION_FILTER_MAP = {
    AuthorizationFilters.AUTHENTICATED_STAFF_USER: is_staff_user,
}


def resolve_authorization_filter_fn(perm):
    return AUTHORIZATION_FILTER_MAP.get(perm)


def one_of_permissions_or_auth_filter_required(
    context, permissions: Iterable[BasePermissionEnum]
):
    if not permissions:
        return True

    authorization_filters = [
        p for p in permissions if isinstance(p, AuthorizationFilters)
    ]
    permissions = [p for p in permissions if not isinstance(p, AuthorizationFilters)]

    granted_by_permissions = False
    granted_by_authorization_filters = False

    requestor = context.user

    if requestor and permissions:
        perm_checks_results = []
        for permission in permissions:
            perm_checks_results.append(requestor.has_perm(permission))
        granted_by_permissions = any(perm_checks_results)

    if authorization_filters:
        auth_filters_results = []
        for p in authorization_filters:
            perm_fn = resolve_authorization_filter_fn(p)
            if perm_fn:
                res = perm_fn(context)
                auth_filters_results.append(bool(res))
        granted_by_authorization_filters = any(auth_filters_results)

    return granted_by_permissions or granted_by_authorization_filters
