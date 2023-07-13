import binascii
import logging
import traceback
from enum import Enum
from typing import Any, Dict, Union
from uuid import UUID

import graphene
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Q
from graphene import ObjectType
from graphql import GraphQLError
from graphql.error import format_error as format_graphql_error
from jwt import InvalidTokenError

from ..exceptions import PermissionDenied, ReadOnlyException

ERROR_COULD_NO_RESOLVE_GLOBAL_ID = (
    "Could not resolve to a node with the global id list of '%s'."
)
REVERSED_DIRECTION = {
    "-": "",
    "": "-",
}

unhandled_errors_logger = logging.getLogger("saleor.graphql.errors.unhandled")
handled_errors_logger = logging.getLogger("saleor.graphql.errors.handled")

ALLOWED_ERRORS = [
    GraphQLError,
    InvalidTokenError,
    PermissionDenied,
    ReadOnlyException,
    ValidationError,
]


def from_global_id_or_error(
    id: str, only_type: Union[ObjectType, str, None] = None, field: str = "id"
):
    try:
        _type, _id = graphene.Node.from_global_id(id)
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise GraphQLError(f"Couldn't resolve id: {id}.")

    if only_type and str(_type) != str(only_type):
        raise GraphQLError(f"Must receive a {only_type} id.")
    return _type, _id


def from_global_id_or_none(
    global_id,
    only_type: Union[graphene.ObjectType, str, None] = None,
    raise_error: bool = False,
):
    if not global_id:
        return None

    return from_global_id_or_error(global_id, only_type, raise_error)[1]


def resolve_global_ids_to_primary_keys(
    ids, graphene_type=None, raise_error: bool = False
):
    pks = []
    invalid_ids = []
    used_type = graphene_type

    for graphql_id in ids:
        if not graphql_id:
            invalid_ids.append(graphql_id)
            continue

        try:
            node_type, _id = from_global_id_or_error(graphql_id)
        except Exception:
            invalid_ids.append(graphql_id)
            continue

        # Raise GraphQL error if ID of a different type was passed
        if used_type and str(used_type) != str(node_type):
            if not raise_error:
                continue
            raise GraphQLError(f"Must receive {str(used_type)} id: {graphql_id}.")

        used_type = node_type
        pks.append(_id)

    if invalid_ids:
        raise GraphQLError(ERROR_COULD_NO_RESOLVE_GLOBAL_ID % invalid_ids)

    return used_type, pks


def _resolve_graphene_type(schema, type_name):
    type_from_schema = schema.get_type(type_name)
    if type_from_schema:
        return type_from_schema.graphene_type
    raise GraphQLError("Could not resolve the type {}".format(type_name))


def get_nodes(
    ids,
    graphene_type: Union[graphene.ObjectType, str, None] = None,
    model=None,
    qs=None,
    schema=None,
):
    """Return a list of nodes.

    If the `graphene_type` argument is provided, the IDs will be validated
    against this type. If the type was not provided, it will be looked up in
    the schema. Raises an error if not all IDs are of the same
    type.

    If the `graphene_type` is of type str, the model keyword argument must be provided.
    """
    nodes_type, pks = resolve_global_ids_to_primary_keys(
        ids, graphene_type, raise_error=True
    )
    # If `graphene_type` was not provided, check if all resolved types are
    # the same. This prevents from accidentally mismatching IDs of different
    # types.
    if nodes_type and not graphene_type:
        if schema:
            graphene_type = _resolve_graphene_type(schema, nodes_type)
        else:
            raise GraphQLError("GraphQL schema was not provided")

    if qs is None and graphene_type and not isinstance(graphene_type, str):
        qs = graphene_type._meta.model.objects
    elif model is not None:
        qs = model.objects

    nodes = list(qs.filter(pk__in=pks)) if qs else []
    nodes.sort(key=lambda e: pks.index(str(e.pk)))  # preserve order in pks

    if not nodes:
        raise GraphQLError(ERROR_COULD_NO_RESOLVE_GLOBAL_ID % ids)

    nodes_pk_list = [str(node.pk) for node in nodes]
    for pk in pks:
        assert pk in nodes_pk_list, "There is no node of type {} with pk {}".format(
            graphene_type, pk
        )
    return nodes


def _get_node_for_types_with_double_id(qs, pks, graphene_type):
    uuid_pks = []
    old_pks = []
    is_order_type = str(graphene_type) == "Order"

    for pk in pks:
        try:
            uuid_pks.append(UUID(str(pk)))
        except ValueError:
            old_pks.append(pk)
    if is_order_type:
        lookup = Q(id__in=uuid_pks) | (Q(use_old_id=True) & Q(number__in=old_pks))
    else:
        lookup = Q(id__in=uuid_pks) | (Q(old_id__isnull=False) & Q(old_id__in=old_pks))
    nodes = list(qs.filter(lookup))
    old_id_field = "number" if is_order_type else "old_id"
    return sorted(
        nodes,
        key=lambda e: pks.index(
            str(e.pk) if e.pk in uuid_pks else str(getattr(e, old_id_field))
        ),
    )  # preserve order in pks


def format_error(error, handled_exceptions):
    result: Dict[str, Any]
    if isinstance(error, GraphQLError):
        result = format_graphql_error(error)
    else:
        result = {"message": str(error)}

    if "extensions" not in result:
        result["extensions"] = {}

    exc = error
    while isinstance(exc, GraphQLError) and hasattr(exc, "original_error"):
        exc = exc.original_error
    if isinstance(exc, AssertionError):
        exc = GraphQLError(str(exc))
    if isinstance(exc, handled_exceptions):
        handled_errors_logger.info("A query had an error", exc_info=exc)
    else:
        unhandled_errors_logger.error("A query failed unexpectedly", exc_info=exc)

    # If DEBUG mode is disabled we allow only certain error messages to be returned in
    # the API. This prevents from leaking internals that might be included in Python
    # exceptions' error messages.
    is_allowed_err = type(exc) in ALLOWED_ERRORS or any(
        [isinstance(exc, allowed_err) for allowed_err in ALLOWED_ERRORS]
    )
    if not is_allowed_err and not settings.DEBUG:
        result["message"] = "Internal Server Error"

    result["extensions"]["exception"] = {"code": type(exc).__name__}
    if settings.DEBUG:
        lines = []

        if isinstance(exc, BaseException):
            for line in traceback.format_exception(type(exc), exc, exc.__traceback__):
                lines.extend(line.rstrip().splitlines())
        result["extensions"]["exception"]["stacktrace"] = lines
    return result


def snake_to_camel_case(name):
    if isinstance(name, str):
        split_name = name.split("_")
        return split_name[0] + "".join(map(str.capitalize, split_name[1:]))
    return name


DJANGO_VALIDATORS_ERROR_CODES = [
    "invalid",
    "invalid_extension",
    "limit_value",
    "max_decimal_places",
    "max_digits",
    "max_length",
    "max_value",
    "max_whole_digits",
    "min_length",
    "min_value",
    "null_characters_not_allowed",
]

DJANGO_FORM_FIELDS_ERROR_CODES = [
    "contradiction",
    "empty",
    "incomplete",
    "invalid_choice",
    "invalid_date",
    "invalid_image",
    "invalid_list",
    "invalid_time",
    "missing",
    "overflow",
]


def get_error_code_from_error(error) -> str:
    code = error.code
    if code in ["required", "blank", "null"]:
        return "required"
    if code in ["unique", "unique_for_date"]:
        return "unique"
    if code in DJANGO_VALIDATORS_ERROR_CODES or code in DJANGO_FORM_FIELDS_ERROR_CODES:
        return "invalid"
    if isinstance(code, Enum):
        code = code.value
    return code
