from __future__ import annotations

import asyncio
import json
import queue
from datetime import timedelta
from enum import Enum
from typing import (TYPE_CHECKING,
                    Any,
                    Dict,
                    List,
                    Optional,
                    Union)

from couchbase._utils import JSONType
from couchbase.exceptions import (PYCBC_ERROR_MAP,
                                  CouchbaseException,
                                  ErrorMapper,
                                  ExceptionMap,
                                  InvalidArgumentException)
from couchbase.options import QueryOptions, UnsignedInt64
from couchbase.pycbc_core import n1ql_query
from couchbase.serializer import DefaultJsonSerializer, Serializer

if TYPE_CHECKING:
    from couchbase.mutation_state import MutationState  # noqa: F401


class QueryScanConsistency(Enum):
    """
    For use with :attr:`~._N1QLQuery.consistency`, will allow cached
    values to be returned. This will improve performance but may not
    reflect the latest data in the server.
    """

    NOT_BOUNDED = "not_bounded"
    REQUEST_PLUS = "request_plus"
    AT_PLUS = "at_plus"


class QueryProfile(Enum):
    OFF = "off"
    PHASES = "phases"
    TIMINGS = "timings"


class QueryStatus(Enum):
    RUNNING = ()
    SUCCESS = ()
    ERRORS = ()
    COMPLETED = ()
    STOPPED = ()
    TIMEOUT = ()
    CLOSED = ()
    FATAL = ()
    ABORTED = ()
    UNKNOWN = ()


class QueryProblem(object):
    def __init__(self, raw):
        self._raw = raw

    def code(self) -> int:
        return self._raw.get("code", None)

    def message(self) -> str:
        return self._raw.get("message", None)


class QueryWarning(QueryProblem):
    def __init__(self, query_warning  # type: QueryProblem
                 ):
        super().__init__(query_warning)

    def __repr__(self):
        return "QueryWarning:{}".format(super()._raw)


class QueryError(QueryProblem):
    def __init__(self, query_error  # type: QueryProblem
                 ):
        super().__init__(query_error)

    def __repr__(self):
        return "QueryError:{}".format(super()._raw)


class QueryMetrics(object):
    def __init__(self, raw  # type: Dict[str, Any]
                 ) -> None:
        self._raw = raw

    @property
    def _raw_metrics(self):
        return self._raw

    def elapsed_time(self) -> timedelta:
        us = self._raw.get("elapsed_time") / 1000
        return timedelta(microseconds=us)

    def execution_time(self) -> timedelta:
        us = self._raw.get("execution_time") / 1000
        return timedelta(microseconds=us)

    def sort_count(self) -> UnsignedInt64:
        return UnsignedInt64(self._raw.get("sort_count", 0))

    def result_count(self) -> UnsignedInt64:
        return UnsignedInt64(self._raw.get("result_count", 0))

    def result_size(self) -> UnsignedInt64:
        return UnsignedInt64(self._raw.get("result_size", 0))

    def mutation_count(self) -> UnsignedInt64:
        return UnsignedInt64(self._raw.get("mutation_count", 0))

    def error_count(self) -> UnsignedInt64:
        return UnsignedInt64(self._raw.get("error_count", 0))

    def warning_count(self) -> UnsignedInt64:
        return UnsignedInt64(self._raw.get("warning_count", 0))

    def __repr__(self):
        return "QueryMetrics:{}".format(self._raw)


class QueryMetaData:
    def __init__(self, raw  # type: Dict[str, Any]
                 ) -> None:
        if raw is not None:
            self._raw = raw.get('metadata', None)
        else:
            self._raw = None

    def request_id(self) -> str:
        return self._raw.get("request_id", None)

    def client_context_id(self) -> str:
        return self._raw.get("client_context_id", None)

    def status(self) -> QueryStatus:
        return QueryStatus[self._raw.get("status", "unknown").upper()]

    def signature(self) -> Optional[JSONType]:
        return self._raw.get("signature", None)

    def warnings(self) -> List[QueryWarning]:
        return list(
            map(QueryWarning, self._raw.get("warnings", []))
        )

    def errors(self) -> List[QueryError]:
        return list(
            map(QueryError, self._raw.get("errors", []))
        )

    def metrics(self) -> Optional[QueryMetrics]:
        print(f'get metrics: {self._raw}')
        if "metrics" in self._raw:
            print(f'getting metrics: {self._raw}')
            return QueryMetrics(self._raw.get("metrics", {}))
        return None

    def profile(self) -> Optional[JSONType]:
        return self._raw.get("profile", None)

    def __repr__(self):
        return "QueryMetadata:{}".format(self._raw)


class N1QLQuery:

    # empty transform will skip updating the attribute when creating an
    # N1QLQuery object
    _VALID_OPTS = {
        "timeout": {"timeout": timedelta.total_seconds},
        "read_only": {"readonly": lambda x: x},
        "scan_consistency": {"consistency": lambda x: x},
        "consistent_with": {"consistent_with": lambda x: x},
        "adhoc": {"adhoc": lambda x: x},
        "client_context_id": {"client_context_id": lambda x: x},
        "max_parallelism": {"max_parallelism": lambda x: x},
        "pipeline_batch": {"pipeline_batch": lambda x: x},
        "pipeline_cap": {"pipeline_cap": lambda x: x},
        "profile": {"profile": lambda x: x},
        "query_context": {"query_context": lambda x: x},
        "raw": {"raw": lambda x: x},
        "scap_cap": {"raw": lambda x: x},
        "scap_wait": {"scap_wait": timedelta.total_seconds},
        "metrics": {"metrics": lambda x: x},
        "flex_index": {"flex_index": lambda x: x},
        "preserve_expiry": {"preserve_expiry": lambda x: x},
        "positional_parameters": {},
        "named_parameters": {},
    }

    def __init__(self, query, *args, **kwargs):

        self._params = {"statement": query}
        self._raw = None
        if args:
            self._add_pos_args(*args)
        if kwargs:
            self._set_named_args(**kwargs)

    def _set_named_args(self, **kv):
        """
        Set a named parameter in the query. The named field must
        exist in the query itself.

        :param kv: Key-Value pairs representing values within the
            query. These values should be stripped of their leading
            `$` identifier.

        """
        # named_params = {}
        # for k in kv:
        #     named_params["${0}".format(k)] = json.dumps(kv[k])
        # couchbase++ wants all args JSONified
        named_params = {f'${k}': json.dumps(v) for k, v in kv.items()}

        arg_dict = self._params.setdefault("named_parameters", {})
        arg_dict.update(named_params)
        # return self

    def _add_pos_args(self, *args):
        """
        Set values for *positional* placeholders (``$1,$2,...``)

        :param args: Values to be used
        """
        arg_array = self._params.setdefault("positional_parameters", [])
        # couchbase++ wants all args JSONified
        json_args = [json.dumps(arg) for arg in args]
        arg_array.extend(json_args)

    def set_option(self, name, value):
        """
        Set a raw option in the query. This option is encoded
        as part of the query parameters without any client-side
        verification. Use this for settings not directly exposed
        by the Python client.

        :param name: The name of the option
        :param value: The value of the option
        """
        self._params[name] = value

    @property
    def params(self) -> Dict[str, Any]:
        return self._params

    @property
    def metrics(self) -> bool:
        return self._params.get('metrics', False)

    @metrics.setter
    def metrics(self, value  # type: bool
                ) -> None:
        self.set_option('metrics', value)

    @property
    def statement(self) -> str:
        return self._params['statement']

    @property
    def timeout(self) -> Optional[float]:
        value = self._params.get('timeout', None)
        if not value:
            return None
        value = value[:-1]
        return float(value)

    @timeout.setter
    def timeout(self, value  # type: Union[timedelta,float]
                ) -> None:
        if not value:
            self._params.pop('timeout', 0)
        else:
            if not isinstance(value, (timedelta, float)):
                raise InvalidArgumentException(message="Excepted timeout to be a timedelta | float")
            if isinstance(value, timedelta):
                self.set_option('timeout', value.total_seconds())
            else:
                self.set_option('timeout', value)

    @property
    def readonly(self) -> bool:
        return self._params.get('readonly', False)

    @readonly.setter
    def readonly(self, value  # type: bool
                 ) -> None:
        self._params['readonly'] = value

    @property
    def consistency(self) -> QueryScanConsistency:
        value = self._params.get(
            'scan_consistency', None
        )
        if value is None and 'mutation_state' in self._params:
            return QueryScanConsistency.AT_PLUS
        if value is None:
            return QueryScanConsistency.NOT_BOUNDED
        if isinstance(value, str):
            return QueryScanConsistency.REQUEST_PLUS if value == 'request_plus' else QueryScanConsistency.NOT_BOUNDED

    @consistency.setter
    def consistency(self, value  # type: Union[QueryScanConsistency, str]
                    ) -> None:
        invalid_argument = False
        if 'mutation_state' not in self._params:
            if isinstance(value, QueryScanConsistency):
                if value == QueryScanConsistency.AT_PLUS:
                    invalid_argument = True
                else:
                    self.set_option('scan_consistency', value.value)
            elif isinstance(value, str) and value in [sc.value for sc in QueryScanConsistency]:
                if value == QueryScanConsistency.AT_PLUS.value:
                    invalid_argument = True
                else:
                    self.set_option('scan_consistency', value)
            else:
                raise InvalidArgumentException(message=("Excepted consistency to be either of type "
                                                        "QueryScanConsistency or str representation "
                                                        "of QueryScanConsistency"))

        if invalid_argument:
            raise InvalidArgumentException(message=("Cannot set consistency to AT_PLUS.  Use "
                                                    "consistent_with instead or set consistency "
                                                    "to NOT_BOUNDED or REQUEST_PLUS"))

    @property
    def consistent_with(self):
        return {
            'consistency': self.consistency,
            'scan_vectors': self._params.get('mutation_state', None)
        }

    @consistent_with.setter
    def consistent_with(self, value  # type: MutationState
                        ):
        """
        Indicate that the query should be consistent with one or more
        mutations.

        :param value: The state of the mutations it should be consistent
            with.
        :type state: :class:`~.couchbase.mutation_state.MutationState`
        """
        if self.consistency != QueryScanConsistency.NOT_BOUNDED:
            raise TypeError(
                'consistent_with not valid with other consistency options')

        # avoid circular import
        from couchbase.mutation_state import MutationState  # noqa: F811
        if not (isinstance(value, MutationState) and len(value._sv) > 0):
            raise TypeError('Passed empty or invalid state')
        # 3.x SDK had to set the consistency, couchbase++ will take care of that for us
        self._params.pop('scan_consistency', None)
        self.set_option('mutation_state', list(value._sv))

    @property
    def adhoc(self) -> bool:
        return self._params.get('adhoc', True)

    @adhoc.setter
    def adhoc(self, value  # type: bool
              ) -> None:
        self.set_option('adhoc', value)

    @property
    def client_context_id(self) -> Optional[str]:
        return self._params.get('client_context_id', None)

    @client_context_id.setter
    def client_context_id(self, value  # type: str
                          ) -> None:
        self.set_option('client_context_id', value)

    @property
    def max_parallelism(self) -> Optional[int]:
        return self._params.get('max_parallelism', None)

    @max_parallelism.setter
    def max_parallelism(self, value  # type: int
                        ) -> None:
        self.set_option('max_parallelism', value)

    @property
    def pipeline_batch(self) -> Optional[int]:
        return self._params.get('pipeline_batch', None)

    @pipeline_batch.setter
    def pipeline_batch(self, value  # type: int
                       ) -> None:
        self.set_option('pipeline_batch', value)

    @property
    def pipeline_cap(self) -> Optional[int]:
        return self._params.get('pipeline_cap', None)

    @pipeline_cap.setter
    def pipeline_cap(self, value  # type: int
                     ) -> None:
        self.set_option('pipeline_cap', value)

    @property
    def profile(self) -> QueryProfile:
        return self._params.get(
            'profile_mode', QueryProfile.OFF
        )

    @profile.setter
    def profile(self, value  # type: Union[QueryProfile, str]
                ) -> None:
        if isinstance(value, QueryProfile):
            self.set_option('profile_mode', value.value)
        elif isinstance(value, str) and value in [pm.value for pm in QueryProfile]:
            self.set_option('profile_mode', value)
        else:
            raise InvalidArgumentException(message=("Excepted profile to be either of type "
                                                    "QueryProfile or str representation of QueryProfile"))

    @property
    def query_context(self) -> Optional[str]:
        return self._params.get('scope_qualifier', None)

    @query_context.setter
    def query_context(self, value  # type: str
                      ) -> None:
        self.set_option('scope_qualifier', value)

    @property
    def send_to_node(self) -> Optional[str]:
        return self._params.get('send_to_node', None)

    @send_to_node.setter
    def send_to_node(self, value  # type: str
                     ) -> None:
        self.set_option('send_to_node', value)

    @property
    def scap_cap(self) -> Optional[int]:
        return self._params.get('scap_cap', None)

    @scap_cap.setter
    def scap_cap(self, value  # type: int
                 ) -> None:
        self.set_option('scap_cap', value)

    @property
    def scan_wait(self) -> Optional[float]:
        value = self._params.get('scan_wait', None)
        if not value:
            return None
        value = value[:-1]
        return float(value)

    @scan_wait.setter
    def scan_wait(self, value  # type: timedelta
                  ) -> None:
        if not value:
            self._params.pop('scan_wait', 0)
        else:
            if not isinstance(value, timedelta):
                raise InvalidArgumentException(message="Excepted scan_wait to be a timedelta")

            self.set_option('scan_wait', value.total_seconds())

    @property
    def flex_index(self) -> bool:
        return self._params.get('flex_index', False)

    @flex_index.setter
    def flex_index(self, value  # type: bool
                   ) -> None:
        self.set_option('flex_index', value)

    @property
    def preserve_expiry(self) -> bool:
        return self._params.get('preserve_expiry', False)

    @preserve_expiry.setter
    def preserve_expiry(self, value  # type: bool
                        ) -> None:
        self.set_option('preserve_expiry', value)

    @property
    def raw(self) -> Optional[Dict[str, Any]]:
        return self._params.get('raw', None)

    @raw.setter
    def raw(self, value  # type: Dict[str, Any]
            ) -> None:
        if not isinstance(value, dict):
            raise TypeError("Raw option must be of type Dict[str, Any].")
        for k in value.keys():
            if not isinstance(k, str):
                raise TypeError("key for raw value must be str")
        raw_params = {f'{k}': json.dumps(v) for k, v in value.items()}
        self.set_option('raw', raw_params)

    @property
    def serializer(self) -> Optional[Serializer]:
        return self._params.get('serializer', None)

    @serializer.setter
    def serializer(self, value  # type: Serializer
                   ):
        if not issubclass(value, Serializer):
            raise InvalidArgumentException(message='Serializer should implement Serializer interface.')
        self.set_option('serializer', value)

    @classmethod
    def create_query_object(cls, statement, *options, **kwargs):
        # lets make a copy of the options, and update with kwargs...
        opt = QueryOptions()
        # TODO: is it possible that we could have [QueryOptions, QueryOptions, ...]??
        #       If so, why???
        opts = list(options)
        for o in opts:
            if isinstance(o, QueryOptions):
                opt = o
                opts.remove(o)
        args = opt.copy()
        args.update(kwargs)

        # now lets get positional parameters.  Actual positional
        # params OVERRIDE positional_parameters
        positional_parameters = args.pop("positional_parameters", [])
        if opts and len(opts) > 0:
            positional_parameters = opts

        # now the named parameters.  NOTE: all the kwargs that are
        # not VALID_OPTS must be named parameters, and the kwargs
        # OVERRIDE the list of named_parameters
        new_keys = list(filter(lambda x: x not in cls._VALID_OPTS, args.keys()))
        named_parameters = args.pop("named_parameters", {})
        for k in new_keys:
            named_parameters[k] = args[k]

        query = cls(statement, *positional_parameters, **named_parameters)
        # now lets try to setup the options.
        # but for now we will use the existing N1QLQuery.  Could be we can
        # add to it, etc...

        # default to false on metrics
        query.metrics = args.get("metrics", False)

        for k, v in ((k, args[k]) for k in (args.keys() & cls._VALID_OPTS)):
            for target, transform in cls._VALID_OPTS[k].items():
                setattr(query, target, transform(v))
        return query


class QueryRequestLogic:
    def __init__(self,
                 connection,
                 query_params,
                 row_factory=lambda x: x,
                 **kwargs
                 ):

        self._connection = connection
        self._query_params = query_params
        self.row_factory = row_factory
        self._rows = asyncio.Queue()
        self._raw_rows = queue.Queue()
        self._query_request_ftr = None
        self._ROWS_STOP = object()
        self._streaming_result = None
        self._started_streaming = False
        self._done_streaming = False
        self._metadata = None
        self._serializer = None

    @property
    def params(self) -> Dict[str, Any]:
        return self._query_params

    @property
    def serializer(self) -> Serializer:
        if self._serializer:
            return self._serializer

        serializer = self.params.get('serializer', None)
        if not serializer:
            serializer = DefaultJsonSerializer()

        self._serializer = serializer
        return self._serializer

    @property
    def started_streaming(self) -> bool:
        return self._started_streaming

    @property
    def done_streaming(self) -> bool:
        return self._done_streaming

    def metadata(self):
        # @TODO:  raise if query isn't complete?
        return self._metadata

    def _handle_query_result_exc(self, query_response):
        base_exc = query_response.raw_result.get('exc', None)
        exc_info = query_response.raw_result.get('exc_info', None)

        excptn = None
        if base_exc is None and exc_info:
            exc_cls = PYCBC_ERROR_MAP.get(exc_info.get('error_code', None), CouchbaseException)
            new_exc_info = {k: v for k, v in exc_info if k in ['cinfo', 'inner_cause']}
            excptn = exc_cls(message=exc_info.get('message', None), exc_info=new_exc_info)
        else:
            err_ctx = base_exc.error_context()
            if err_ctx is not None:
                print(base_exc.err())
                print(f'err context: {err_ctx}')
                print(f'err info: {exc_info}')
                excptn = ErrorMapper.parse_error_context(base_exc)
            else:
                exc_cls = PYCBC_ERROR_MAP.get(base_exc.err(), CouchbaseException)
                excptn = exc_cls(message=base_exc.strerror())

        if excptn is None:
            exc_cls = PYCBC_ERROR_MAP.get(ExceptionMap.InternalSDKException.value, CouchbaseException)
            excptn = exc_cls(message='Unknown error.')

        raise excptn

    def _set_metadata(self, query_response):
        has_exception = query_response.raw_result.get('has_exception', None)
        if has_exception:
            self._handle_query_result_exc(query_response)

        self._metadata = QueryMetaData(query_response.raw_result.get('value', None))
        # metadata = query_response.get('metadata', None)
        # if metadata:
        #     #print(f'metadata: {metadata}')
        #     md = metadata.raw_result.get('value', None)
        #     print(f'metadata: {md}')
        #     self._metadata = QueryMetaData(md)

    # async def handle_query_row(self, row):
    #     print(f'row: {row}')
    #     await self._rows.put(row)
    #     return row

    def _submit_query(self):
        if self.done_streaming:
            return

        self._started_streaming = True
        kwargs = {
            'conn': self._connection,
        }
        kwargs.update(self.params)
        self._streaming_result = n1ql_query(**kwargs)
    # def _submit_query(self):
    #     # print(f'submitting query from thread: {current_thread()}')
    #     if self._query_request_ftr is not None:
    #         return

    #     if self.params.get('serializer', None) is None:
    #         self.params['serializer'] = DefaultJsonSerializer()

    #     kwargs = {
    #         'conn': self._connection,
    #         'callback': self._on_query_complete,
    #         'errback': self._on_query_exception,
    #         **self.params
    #     }
    #     print(f'kwargs: {kwargs}')
    #     self._query_request_ftr = self._loop.create_future()
    #     self._streaming_result = n1ql_query(**kwargs)
    #     # self.params.pop('serializer')
    #     # print('removed serializer from params')

    def _on_query_complete(self, result):
        print(f'_on_query_callback: {result}')
        self._loop.call_soon_threadsafe(self._query_request_ftr.set_result, result)

    def _on_query_exception(self, exc):
        err_ctx = exc.error_context()
        print(f"error context: {err_ctx}")
        if err_ctx is not None:
            excptn = ErrorMapper.parse_error_context(exc)
        else:
            exc_cls = PYCBC_ERROR_MAP.get(exc.err(), CouchbaseException)
            excptn = exc_cls(exc)
        self._loop.call_soon_threadsafe(self._query_request_ftr.set_exception, excptn)

    def __iter__(self):
        raise NotImplementedError(
            'Cannot use synchronous iterator, are you using `async for`?'
        )

    def __aiter__(self):
        raise NotImplementedError(
            'Cannot use asynchronous iterator.'
        )
