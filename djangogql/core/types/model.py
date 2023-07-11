from collections import OrderedDict

import graphene
from django.db.models import Model, Q
from graphene.types.objecttype import ObjectType, ObjectTypeOptions
from graphene.types.utils import yank_fields_from_attrs

from ...utils.fields import get_model_fields
from .model_converter import convert_django_field_with_choices
from .registry import get_global_registry

ALL_FIELDS = "__all__"


def construct_fields(
    model, registry, only_fields, exclude_fields, convert_choices_to_enum
):
    _model_fields = get_model_fields(model)

    fields = OrderedDict()
    for name, field in _model_fields:
        is_not_in_only = (
            only_fields is not None
            and only_fields != ALL_FIELDS
            and name not in only_fields
        )
        # is_already_created = name in options.fields
        is_excluded = (
            exclude_fields is not None and name in exclude_fields
        )  # or is_already_created
        # https://docs.djangoproject.com/en/1.10/ref/models/fields/#django.db.models.ForeignKey.related_query_name
        is_no_backref = str(name).endswith("+")
        if is_not_in_only or is_excluded or is_no_backref:
            # We skip this field if we specify only_fields and is not
            # in there. Or when we exclude this field in exclude_fields.
            # Or when there is no back reference.
            continue

        _convert_choices_to_enum = convert_choices_to_enum
        if not isinstance(_convert_choices_to_enum, bool):
            # then `convert_choices_to_enum` is a list of field names to convert
            if name in _convert_choices_to_enum:
                _convert_choices_to_enum = True
            else:
                _convert_choices_to_enum = False

        converted = convert_django_field_with_choices(
            field, registry, convert_choices_to_enum=_convert_choices_to_enum
        )
        fields[name] = converted

    return fields


class ModelObjectOptions(ObjectTypeOptions):
    model = None


class ModelObjectType(ObjectType):
    @classmethod
    def __init_subclass_with_meta__(
        cls,
        interfaces=(),
        possible_types=(),
        default_resolver=None,
        fields=None,
        exclude=None,
        convert_choices_to_enum=True,
        _meta=None,
        **options,
    ):
        if not _meta:
            _meta = ModelObjectOptions(cls)

        if not getattr(_meta, "model", None):
            if not options.get("model"):
                raise ValueError(
                    "ModelObjectType was declared without 'model' option in it's Meta."
                )
            elif not issubclass(options["model"], Model):
                raise ValueError(
                    "ModelObjectType was declared with invalid 'model' option value "
                    "in it's Meta. Expected subclass of django.db.models.Model, "
                    f"received '{type(options['model'])}' type."
                )

            _meta.model = options.pop("model")

        registry = get_global_registry()
        model = _meta.model

        django_fields = yank_fields_from_attrs(
            construct_fields(model, registry, fields, exclude, convert_choices_to_enum),
            _as=graphene.Field,
        )

        _meta.fields = django_fields

        super(ModelObjectType, cls).__init_subclass_with_meta__(
            interfaces=interfaces,
            possible_types=possible_types,
            default_resolver=default_resolver,
            _meta=_meta,
            **options,
        )

    @classmethod
    def get_node(cls, _, id):
        model = cls._meta.model
        lookup = Q(pk=id)

        try:
            return model.objects.get(lookup)
        except model.DoesNotExist:
            return None

    @classmethod
    def get_model(cls):
        return cls._meta.model
        return cls._meta.model
