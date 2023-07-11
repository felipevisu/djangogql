import re
from collections import OrderedDict
from functools import singledispatch, wraps

import graphene
from django.db import models
from django.utils.encoding import force_str
from graphene.utils.str_converters import to_camel_case
from graphql import GraphQLError
from text_unidecode import unidecode


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


def convert_django_field_with_choices(
    field, registry=None, convert_choices_to_enum=True
):
    if registry is not None:
        converted = registry.get_converted_field(field)
        if converted:
            return converted
    choices = getattr(field, "choices", None)
    if choices and convert_choices_to_enum:
        EnumCls = convert_choice_field_to_enum(field)
        required = not (field.blank or field.null)

        converted = EnumCls(
            description=get_django_field_description(field), required=required
        ).mount_as(BlankValueField)
    else:
        converted = convert_django_field(field, registry)
    if registry is not None:
        registry.register_converted_field(field, converted)
    return converted


def get_django_field_description(field):
    return str(field.help_text) if field.help_text else None


@singledispatch
def convert_django_field(field, registry=None):
    raise Exception(
        "Don't know how to convert the Django field {} ({})".format(
            field, field.__class__
        )
    )


@convert_django_field.register(models.CharField)
@convert_django_field.register(models.TextField)
@convert_django_field.register(models.EmailField)
@convert_django_field.register(models.SlugField)
@convert_django_field.register(models.URLField)
@convert_django_field.register(models.GenericIPAddressField)
@convert_django_field.register(models.FileField)
@convert_django_field.register(models.FilePathField)
def convert_field_to_string(field, registry=None):
    return graphene.String(
        description=get_django_field_description(field), required=not field.null
    )


@convert_django_field.register(models.BigAutoField)
@convert_django_field.register(models.AutoField)
def convert_field_to_id(field, registry=None):
    return graphene.ID(
        description=get_django_field_description(field), required=not field.null
    )


if hasattr(models, "SmallAutoField"):

    @convert_django_field.register(models.SmallAutoField)
    def convert_field_small_to_id(field, registry=None):
        return convert_field_to_id(field, registry)


@convert_django_field.register(models.UUIDField)
def convert_field_to_uuid(field, registry=None):
    return graphene.UUID(
        description=get_django_field_description(field), required=not field.null
    )


@convert_django_field.register(models.PositiveIntegerField)
@convert_django_field.register(models.PositiveSmallIntegerField)
@convert_django_field.register(models.SmallIntegerField)
@convert_django_field.register(models.IntegerField)
def convert_field_to_int(field, registry=None):
    return graphene.Int(
        description=get_django_field_description(field), required=not field.null
    )


@convert_django_field.register(models.BooleanField)
def convert_field_to_boolean(field, registry=None):
    return graphene.Boolean(
        description=get_django_field_description(field), required=not field.null
    )


@convert_django_field.register(models.DecimalField)
def convert_field_to_decimal(field, registry=None):
    return graphene.Decimal(
        description=get_django_field_description(field), required=not field.null
    )


@convert_django_field.register(models.FloatField)
@convert_django_field.register(models.DurationField)
def convert_field_to_float(field, registry=None):
    return graphene.Float(
        description=get_django_field_description(field), required=not field.null
    )


@convert_django_field.register(models.DateTimeField)
def convert_datetime_to_string(field, registry=None):
    return graphene.DateTime(
        description=get_django_field_description(field), required=not field.null
    )


@convert_django_field.register(models.DateField)
def convert_date_to_string(field, registry=None):
    return graphene.Date(
        description=get_django_field_description(field), required=not field.null
    )


@convert_django_field.register(models.TimeField)
def convert_time_to_string(field, registry=None):
    return graphene.Time(
        description=get_django_field_description(field), required=not field.null
    )


@convert_django_field.register(models.ManyToManyField)
@convert_django_field.register(models.ManyToManyRel)
@convert_django_field.register(models.ManyToOneRel)
@convert_django_field.register(models.ForeignKey)
@convert_django_field.register(models.JSONField)
def convert_field_to_list_or_connection(field, registry=None):
    return None