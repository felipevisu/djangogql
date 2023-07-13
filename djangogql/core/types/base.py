from graphene.types.inputobjecttype import InputObjectType
from graphene.types.objecttype import ObjectType


class BaseObjectType(ObjectType):
    @classmethod
    def __init_subclass_with_meta__(
        cls,
        interfaces=(),
        possible_types=(),
        default_resolver=None,
        _meta=None,
        **options,
    ):
        super(BaseObjectType, cls).__init_subclass_with_meta__(
            interfaces=interfaces,
            possible_types=possible_types,
            default_resolver=default_resolver,
            _meta=_meta,
            **options,
        )


class BaseInputObjectType(InputObjectType):
    @classmethod
    def __init_subclass_with_meta__(cls, container=None, _meta=None, **options):
        super(BaseInputObjectType, cls).__init_subclass_with_meta__(
            container=container, _meta=_meta, **options
        )
