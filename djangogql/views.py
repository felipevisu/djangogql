import hashlib
import json
from inspect import isclass
from typing import Any, Dict, List, Optional, Tuple, Union

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.functional import SimpleLazyObject
from django.views.generic import View
from graphql import GraphQLDocument, get_default_backend
from graphql.error import GraphQLError, GraphQLSyntaxError
from graphql.execution import ExecutionResult
from jwt.exceptions import PyJWTError

from .context import get_context_value
from .exceptions import PermissionDenied, ReadOnlyException
from .settings import djangogql_settings
from .utils import format_error
from .utils.files import place_files_in_operations

INT_ERROR_MSG = "Int cannot represent non 32-bit signed integer value"
API_PATH = SimpleLazyObject(lambda: reverse("api"))


class GraphQLView(View):
    schema = None
    executor = None
    middleware = None
    root_value = None

    HANDLED_EXCEPTIONS = (GraphQLError, PyJWTError, ReadOnlyException, PermissionDenied)

    def __init__(
        self,
        schema=None,
        executor=None,
        middleware: Optional[List[str]] = None,
        root_value=None,
        backend=None,
    ):
        super().__init__()
        if backend is None:
            backend = get_default_backend()
        if middleware is None:
            middleware = djangogql_settings.MIDDLEWARE
        self.schema = self.schema or schema
        if middleware is not None:
            self.middleware = list(instantiate_middleware(middleware))
        self.executor = executor
        self.root_value = root_value
        self.backend = backend

    def dispatch(self, request, *args, **kwargs):
        if request.method == "GET":
            if djangogql_settings.PLAYGROUND_ENABLED:
                return self.render_playground(request)
            return HttpResponseNotAllowed(["OPTIONS", "POST"])
        elif request.method == "POST":
            return self.handle_query(request)
        else:
            if djangogql_settings.PLAYGROUND_ENABLED:
                return HttpResponseNotAllowed(["GET", "OPTIONS", "POST"])
            else:
                return HttpResponseNotAllowed(["OPTIONS", "POST"])

    def render_playground(self, request):
        return render(
            request,
            "graphql/playground.html",
            {
                "api_url": request.build_absolute_uri(str(API_PATH)),
                "plugins_url": request.build_absolute_uri("/plugins/"),
            },
        )

    def _handle_query(self, request: HttpRequest) -> JsonResponse:
        try:
            data = self.parse_body(request)
        except ValueError:
            return JsonResponse(
                data={"errors": [self.format_error("Unable to parse query.")]},
                status=400,
            )

        if isinstance(data, list):
            responses = [self.get_response(request, entry) for entry in data]
            result: Union[list, Optional[dict]] = [
                response for response, code in responses
            ]
            status_code = max((code for response, code in responses), default=200)
        else:
            result, status_code = self.get_response(request, data)
        return JsonResponse(data=result, status=status_code, safe=False)

    def handle_query(self, request: HttpRequest) -> JsonResponse:
        response = self._handle_query(request)
        return response

    def get_response(
        self, request: HttpRequest, data: dict
    ) -> Tuple[Optional[Dict[str, List[Any]]], int]:
        execution_result = self.execute_graphql_request(request, data)
        status_code = 200
        if execution_result:
            response = {}
            if execution_result.errors:
                response["errors"] = [
                    self.format_error(e) for e in execution_result.errors
                ]
            if execution_result.invalid:
                status_code = 400
            else:
                response["data"] = execution_result.data
            if execution_result.extensions:
                response["extensions"] = execution_result.extensions
            result: Optional[Dict[str, List[Any]]] = response
        else:
            result = None

        return result, status_code

    def get_root_value(self):
        return self.root_value

    def parse_query(
        self, query: Optional[str]
    ) -> Tuple[Optional[GraphQLDocument], Optional[ExecutionResult]]:
        if not query or not isinstance(query, str):
            return (
                None,
                ExecutionResult(
                    errors=[GraphQLError("Must provide a query string.")], invalid=True
                ),
            )
        try:
            return (
                self.backend.document_from_string(self.schema, query),
                None,
            )
        except (ValueError, GraphQLSyntaxError) as e:
            return None, ExecutionResult(errors=[e], invalid=True)

    def check_if_query_contains_only_schema(self, document: GraphQLDocument):
        query_with_schema = False
        for definition in document.document_ast.definitions:
            selections = definition.selection_set.selections
            selection_count = len(selections)
            for selection in selections:
                selection_name = str(selection.name.value)
                if selection_name == "__schema":
                    query_with_schema = True
                    if selection_count > 1:
                        msg = "`__schema` must be fetched in separate query"
                        raise GraphQLError(msg)
        return query_with_schema

    def execute_graphql_request(self, request: HttpRequest, data: dict):
        query, variables, operation_name = self.get_graphql_params(request, data)

        document, error = self.parse_query(query)
        if error or document is None:
            return error

        raw_query_string = document.document_string

        try:
            query_contains_schema = self.check_if_query_contains_only_schema(document)
        except GraphQLError as e:
            return ExecutionResult(errors=[e], invalid=True)

        extra_options: Dict[str, Optional[Any]] = {}

        if self.executor:
            # We only include it optionally since
            # executor is not a valid argument in all backends
            extra_options["executor"] = self.executor
        try:
            response = None
            should_use_cache_for_scheme = query_contains_schema & (not settings.DEBUG)
            if should_use_cache_for_scheme:
                key = generate_cache_key(raw_query_string)
                response = cache.get(key)

            if not response:
                response = document.execute(
                    root=self.get_root_value(),
                    variables=variables,
                    operation_name=operation_name,
                    context=get_context_value(request),
                    middleware=self.middleware,
                    **extra_options,
                )
                if should_use_cache_for_scheme:
                    cache.set(key, response)

            return response
        except Exception as e:
            if str(e).startswith(INT_ERROR_MSG) or isinstance(e, ValueError):
                e = GraphQLError(str(e))
            return ExecutionResult(errors=[e], invalid=True)

    @staticmethod
    def parse_body(request: HttpRequest):
        content_type = request.content_type
        if content_type == "application/graphql":
            return {"query": request.body.decode("utf-8")}
        if content_type == "application/json":
            body = request.body.decode("utf-8")
            return json.loads(body)
        if (
            content_type in ["application/x-www-form-urlencoded", "multipart/form-data"]
            and "operations" in request.POST
        ):
            operations = json.loads(request.POST.get("operations", "{}"))
            files_map = json.loads(request.POST.get("map", "{}"))
            output = place_files_in_operations(operations, files_map, request.FILES)
            return output
        return {}

    @staticmethod
    def get_graphql_params(request: HttpRequest, data: dict):
        query = data.get("query")
        variables = data.get("variables")
        operation_name = data.get("operationName")
        if operation_name == "null":
            operation_name = None
        return query, variables, operation_name

    @classmethod
    def format_error(cls, error):
        return format_error(error, cls.HANDLED_EXCEPTIONS)


def get_key(key):
    try:
        int_key = int(key)
    except (TypeError, ValueError):
        return key
    else:
        return int_key


def get_shallow_property(obj, prop):
    if isinstance(prop, int):
        return obj[prop]
    try:
        return obj.get(prop)
    except AttributeError:
        return None


def obj_set(obj, path, value, do_not_replace):
    if isinstance(path, int):
        path = [path]
    if not path:
        return obj
    if isinstance(path, str):
        new_path = [get_key(part) for part in path.split(".")]
        return obj_set(obj, new_path, value, do_not_replace)

    current_path = path[0]
    current_value = get_shallow_property(obj, current_path)

    if len(path) == 1:
        if current_value is None or not do_not_replace:
            obj[current_path] = value

    if current_value is None:
        try:
            if isinstance(path[1], int):
                obj[current_path] = []
            else:
                obj[current_path] = {}
        except IndexError:
            pass
    return obj_set(obj[current_path], path[1:], value, do_not_replace)


def instantiate_middleware(middlewares):
    for middleware in middlewares:
        if isclass(middleware):
            yield middleware()
            continue
        yield middleware


def generate_cache_key(raw_query: str) -> str:
    hashed_query = hashlib.sha256(str(raw_query).encode("utf-8")).hexdigest()
    return f"graphqlstarter-{hashed_query}"
