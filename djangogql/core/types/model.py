import graphene
from django.db.models import Model, Q
from graphene.types.objecttype import ObjectType, ObjectTypeOptions
from graphene.types.utils import yank_fields_from_attrs
from graphene_django.registry import get_global_registry
from graphene_django.types import construct_fields

ALL_FIELDS = "__all__"


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
