from typing import TYPE_CHECKING, Dict, List, Union

if TYPE_CHECKING:
    from django.db.models import QuerySet


def filter_range_field(qs, field, value):
    gte, lte = value.get("gte"), value.get("lte")
    if gte:
        lookup = {f"{field}__gte": gte}
        qs = qs.filter(**lookup)
    if lte:
        lookup = {f"{field}__lte": lte}
        qs = qs.filter(**lookup)
    return qs


def filter_by_id(object_type):
    from . import resolve_global_ids_to_primary_keys

    def inner(qs, _, value):
        if not value:
            return qs
        _, obj_pks = resolve_global_ids_to_primary_keys(value, object_type)
        return qs.filter(id__in=obj_pks)

    return inner


def filter_by_string_field(
    qs: "QuerySet", field: str, value: Dict[str, Union[str, List[str]]]
):
    eq = value.get("eq")
    one_of = value.get("one_of")
    if eq:
        qs = qs.filter(**{field: eq})
    if one_of:
        qs = qs.filter(**{f"{field}__in": one_of})
    return qs
