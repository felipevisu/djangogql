import binascii
from enum import Enum
from typing import Type, Union

import graphene
from django.core.exceptions import ValidationError
from django.db.models import Model
from django.utils.text import slugify
from graphene import ObjectType
from graphql import GraphQLError


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


def snake_to_camel_case(name):
    if isinstance(name, str):
        split_name = name.split("_")
        return split_name[0] + "".join(map(str.capitalize, split_name[1:]))
    return name


def str_to_enum(name):
    """Create an enum value from a string."""
    return name.replace(" ", "_").replace("-", "_").upper()


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


def generate_unique_slug(
    instance: Type[Model],
    slugable_value: str,
    slug_field_name: str = "slug",
) -> str:
    """Create unique slug for model instance.
    The function uses `django.utils.text.slugify` to generate a slug from
    the `slugable_value` of model field. If the slug already exists it adds
    a numeric suffix and increments it until a unique value is found.
    Args:
        instance: model instance for which slug is created
        slugable_value: value used to create slug
        slug_field_name: name of slug field in instance model
    """
    slug = slugify(slugable_value)
    unique_slug: str = slug

    ModelClass = instance.__class__
    extension = 1

    search_field = f"{slug_field_name}__iregex"
    pattern = rf"{slug}-\d+$|{slug}$"
    slug_values = (
        ModelClass._default_manager.filter(**{search_field: pattern})  # type: ignore
        .exclude(pk=instance.pk)  # type: ignore
        .values_list(slug_field_name, flat=True)
    )

    while unique_slug in slug_values:
        extension += 1
        unique_slug = f"{slug}-{extension}"

    return unique_slug


def validate_slug_and_generate_if_needed(
    instance: Type[Model],
    slugable_field: str,
    cleaned_input: dict,
    slug_field_name: str = "slug",
) -> dict:
    """Validate slug from input and generate in create mutation if is not given."""

    # update mutation - just check if slug value is not empty
    # _state.adding is True only when it's new not saved instance.
    if not instance._state.adding:  # type: ignore
        validate_slug_value(cleaned_input)
        return cleaned_input

    # create mutation - generate slug if slug value is empty
    slug = cleaned_input.get(slug_field_name)
    if not slug and slugable_field in cleaned_input:
        slug = generate_unique_slug(instance, cleaned_input[slugable_field])
        cleaned_input[slug_field_name] = slug
    return cleaned_input


def validate_slug_value(cleaned_input, slug_field_name: str = "slug"):
    if slug_field_name in cleaned_input:
        slug = cleaned_input[slug_field_name]
        if not slug:
            raise ValidationError(
                f"{slug_field_name.capitalize()} value cannot be blank."
            )


def get_duplicates_items(first_list, second_list):
    """Return items that appear on both provided lists."""
    if first_list and second_list:
        return set(first_list) & set(second_list)
    return []


def get_duplicated_values(values):
    """Return set of duplicated values."""
    return {value for value in values if values.count(value) > 1}
