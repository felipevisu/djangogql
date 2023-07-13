import re
from collections import OrderedDict
from functools import singledispatch, wraps

import graphene
from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.utils.encoding import force_str
from graphene.utils.str_converters import to_camel_case
from graphql import GraphQLError
from text_unidecode import unidecode

from ..filters import (
    EnumFilter,
    GlobalIDFormField,
    GlobalIDMultipleChoiceField,
    ListObjectTypeFilter,
    ObjectTypeFilter,
)
from .common import NonNullList


def to_const(string):
    return re.sub(r"[\W|^]+", "_", unidecode(string)).upper()


try:
    from graphql import assert_name
except ImportError:
    # Support for older versions of graphql
    from graphql import assert_valid_name as assert_name


class BlankValueField(graphene.Field):
    def wrap_resolve(self, parent_resolver):
        resolver = self.resolver or parent_resolver

        # create custom resolver
        def blank_field_wrapper(func):
            @wraps(func)
            def wrapped_resolver(*args, **kwargs):
                return_value = func(*args, **kwargs)
                if return_value == "":
                    return None
                return return_value

            return wrapped_resolver

        return blank_field_wrapper(resolver)


def convert_choice_name(name):
    name = to_const(force_str(name))
    try:
        assert_name(name)
    except GraphQLError:
        name = "A_%s" % name
    return name


def get_choices(choices):
    converted_names = []
    if isinstance(choices, OrderedDict):
        choices = choices.items()
    for value, help_text in choices:
        if isinstance(help_text, (tuple, list)):
            yield from get_choices(help_text)
        else:
            name = convert_choice_name(value)
            while name in converted_names:
                name += "_" + str(len(converted_names))
            converted_names.append(name)
            description = str(
                help_text
            )  # TODO: translatable description: https://github.com/graphql-python/graphql-core-next/issues/58
            yield name, value, description


def convert_choices_to_named_enum_with_descriptions(name, choices):
    choices = list(get_choices(choices))
    named_choices = [(c[0], c[1]) for c in choices]
    named_choices_descriptions = {c[0]: c[2] for c in choices}

    class EnumWithDescriptionsType:
        @property
        def description(self):
            return str(named_choices_descriptions[self.name])

    return_type = graphene.Enum(
        name,
        list(named_choices),
        type=EnumWithDescriptionsType,
        description="An enumeration.",
    )
    return return_type


def generate_enum_name(django_model_meta, field):
    name = "{app_label}{object_name}{field_name}Choices".format(
        app_label=to_camel_case(django_model_meta.app_label.title()),
        object_name=django_model_meta.object_name,
        field_name=to_camel_case(field.name.title()),
    )
    return name


def convert_choice_field_to_enum(field, name=None):
    if name is None:
        name = generate_enum_name(field.model._meta, field)
    choices = field.choices
    return convert_choices_to_named_enum_with_descriptions(name, choices)


def convert_field_with_choices(field, registry=None, convert_choices_to_enum=True):
    if registry is not None:
        converted = registry.get_converted_field(field)
        if converted:
            return converted
    choices = getattr(field, "choices", None)
    if choices and convert_choices_to_enum:
        EnumCls = convert_choice_field_to_enum(field)
        required = not (field.blank or field.null)

        converted = EnumCls(
            description=get_field_description(field), required=required
        ).mount_as(BlankValueField)
    else:
        converted = convert_field(field, registry)
    if registry is not None:
        registry.register_converted_field(field, converted)
    return converted


def get_field_description(field):
    return str(field.help_text) if field.help_text else None


def get_field_required(field):
    if hasattr(field, "required"):
        return field.required
    if hasattr(field, "null"):
        return not field.null
    return False


@singledispatch
def convert_field(field):
    raise ImproperlyConfigured(
        "Don't know how to convert the Django form field %s (%s) "
        "to Graphene type" % (field, field.__class__)
    )


@convert_field.register(models.CharField)
@convert_field.register(models.TextField)
@convert_field.register(models.EmailField)
@convert_field.register(models.SlugField)
@convert_field.register(models.URLField)
@convert_field.register(models.GenericIPAddressField)
@convert_field.register(models.FileField)
@convert_field.register(models.FilePathField)
@convert_field.register(forms.CharField)
def convert_field_to_string(field, registry=None):
    return graphene.String(
        description=get_field_description(field), required=get_field_required(field)
    )


@convert_field.register(models.BooleanField)
@convert_field.register(forms.BooleanField)
@convert_field.register(forms.NullBooleanField)
def convert_field_to_nullboolean(field, registry=None):
    return graphene.Boolean(description=get_field_description(field))


@convert_field.register(models.FloatField)
@convert_field.register(models.DurationField)
@convert_field.register(forms.DecimalField)
@convert_field.register(forms.FloatField)
def convert_field_to_float(field, registry=None):
    return graphene.Float(
        description=field.help_text, required=get_field_required(field)
    )


@convert_field.register(ObjectTypeFilter)
@convert_field.register(EnumFilter)
def convert_convert_enum(field, registry=None):
    return field.input_class()


@convert_field.register(models.BigAutoField)
@convert_field.register(models.AutoField)
@convert_field.register(GlobalIDFormField)
def convert_field_to_id(field, registry=None):
    return graphene.ID(required=get_field_required(field))


@convert_field.register(ListObjectTypeFilter)
def convert_list_object_type(field, registry=None):
    return NonNullList(field.input_class)


@convert_field.register(GlobalIDMultipleChoiceField)
def convert_field_to_list(field):
    return NonNullList(graphene.ID, required=get_field_required(field))


@convert_field.register(models.PositiveIntegerField)
@convert_field.register(models.PositiveSmallIntegerField)
@convert_field.register(models.SmallIntegerField)
@convert_field.register(models.IntegerField)
def convert_field_to_int(field, registry=None):
    return graphene.Int(
        description=get_field_description(field), required=not field.null
    )


@convert_field.register(models.DecimalField)
def convert_field_to_decimal(field, registry=None):
    return graphene.Decimal(
        description=get_field_description(field), required=not field.null
    )


@convert_field.register(models.DateTimeField)
def convert_datetime_to_string(field, registry=None):
    return graphene.DateTime(
        description=get_field_description(field), required=not field.null
    )


@convert_field.register(models.DateField)
def convert_date_to_string(field, registry=None):
    return graphene.Date(
        description=get_field_description(field), required=not field.null
    )


@convert_field.register(models.TimeField)
def convert_time_to_string(field, registry=None):
    return graphene.Time(
        description=get_field_description(field), required=not field.null
    )


@convert_field.register(models.ManyToManyField)
@convert_field.register(models.ManyToManyRel)
@convert_field.register(models.ManyToOneRel)
@convert_field.register(models.ForeignKey)
@convert_field.register(models.JSONField)
def convert_field_to_list_or_connection(field, registry=None):
    return None
