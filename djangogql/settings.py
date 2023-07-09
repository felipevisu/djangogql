import importlib
from datetime import timedelta

from django.conf import settings
from django.test.signals import setting_changed

DEFAULTS = {
    "SCHEMA": None,
    "SCHEMA_OUTPUT": "schema.json",
    "MIDDLEWARE": [],
    "PLAYGROUND_ENABLED": True,
    "JWT_EXPIRE": False,
    "JWT_TTL_ACCESS": timedelta(seconds=10),
    "JWT_TTL_APP_ACCESS": timedelta(seconds=10),
    "JWT_TTL_REFRESH": timedelta(days=30),
    "JWT_TTL_REQUEST_EMAIL_CHANGE": timedelta(seconds=3600),
    "PERMISSIONS_ENUMS": []
}

IMPORT_STRINGS = ("MIDDLEWARE", "SCHEMA", "PERMISSIONS_ENUMS")

def perform_import(val, setting_name):
    """
    If the given setting is a string import notation,
    then perform the necessary import or imports.
    """
    if val is None:
        return None
    elif isinstance(val, str):
        return import_from_string(val, setting_name)
    elif isinstance(val, (list, tuple)):
        return [import_from_string(item, setting_name) for item in val]
    return val


def import_from_string(val, setting_name):
    """
    Attempt to import a class from a string representation.
    """
    try:
        parts = val.split(".")
        module_path, class_name = ".".join(parts[:-1]), parts[-1]
        module = importlib.import_module(module_path)
        return getattr(module, class_name)
    except (ImportError, AttributeError) as e:
        msg = "Could not import '{}' for Graphene setting '{}'. {}: {}.".format(
            val,
            setting_name,
            e.__class__.__name__,
            e,
        )
        raise ImportError(msg)


class DjangoGQLSettings:
    def __init__(self, user_settings=None, defaults=None, import_strings=None):
        if user_settings:
            self._user_settings = user_settings
        self.defaults = defaults or DEFAULTS
        self.import_strings = import_strings or IMPORT_STRINGS

    @property
    def user_settings(self):
        if not hasattr(self, "_user_settings"):
            self._user_settings = getattr(settings, "GRAPHENE", {})
        return self._user_settings

    def __getattr__(self, attr):
        if attr not in self.defaults:
            raise AttributeError("Invalid Graphene setting: '%s'" % attr)

        try:
            # Check if present in user settings
            val = self.user_settings[attr]
        except KeyError:
            # Fall back to defaults
            val = getattr(settings, attr, self.defaults[attr])

        # Coerce import strings into classes
        if attr in self.import_strings:
            val = perform_import(val, attr)

        # Cache the result
        setattr(self, attr, val)
        return val
    
djangogql_settings = DjangoGQLSettings(None, DEFAULTS, IMPORT_STRINGS)

def reload_djangogql_settings(*args, **kwargs):
    global djangogql_settings
    setting, value = kwargs["setting"], kwargs["value"]
    if setting == "GRAPHENE":
        djangogql_settings = DjangoGQLSettings(value, DEFAULTS, IMPORT_STRINGS)


setting_changed.connect(reload_djangogql_settings)