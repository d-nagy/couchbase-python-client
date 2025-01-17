from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import (TYPE_CHECKING,
                    Any,
                    Dict,
                    Iterable,
                    Optional)

from couchbase._utils import is_null_or_empty
from couchbase.exceptions import (InvalidArgumentException,
                                  QuotaLimitedException,
                                  SearchIndexNotFoundException)
from couchbase.options import forward_args
from couchbase.pycbc_core import (management_operation,
                                  mgmt_operations,
                                  search_index_mgmt_operations)

if TYPE_CHECKING:
    from couchbase.management.options import (AllowQueryingSearchIndexOptions,
                                              AnalyzeDocumentSearchIndexOptions,
                                              DisallowQueryingSearchIndexOptions,
                                              DropSearchIndexOptions,
                                              FreezePlanSearchIndexOptions,
                                              GetAllSearchIndexesOptions,
                                              GetAllSearchIndexStatsOptions,
                                              GetSearchIndexedDocumentsCountOptions,
                                              GetSearchIndexOptions,
                                              GetSearchIndexStatsOptions,
                                              PauseIngestSearchIndexOptions,
                                              ResumeIngestSearchIndexOptions,
                                              UnfreezePlanSearchIndexOptions,
                                              UpsertSearchIndexOptions)


class SearchIndexManagerLogic:

    _ERROR_MAPPING = {r'.*[iI]ndex not found.*': SearchIndexNotFoundException,
                      r'.*[Cc]reate[Ii]ndex, [Pp]repare failed, err: [Ee]xceeds indexes limit': QuotaLimitedException}

    def __init__(self, connection):
        self._connection = connection

    def upsert_index(self,
                     index,     # type: SearchIndex
                     *options,  # type: UpsertSearchIndexOptions
                     **kwargs   # type: Dict[str, Any]
                     ) -> None:

        if not index:
            raise InvalidArgumentException("expected index to not be None")
        else:
            if not index.is_valid():
                raise InvalidArgumentException(
                    "Index must have name, source set")

        final_args = forward_args(kwargs, *options)
        op_args = {
            'index': index.as_dict()
        }

        if final_args.get("client_context_id", None) is not None:
            op_args["client_context_id"] = final_args.get("client_context_id")

        mgmt_kwargs = {
            "conn": self._connection,
            "mgmt_op": mgmt_operations.SEARCH_INDEX.value,
            "op_type": search_index_mgmt_operations.UPSERT_INDEX.value,
            "op_args": op_args
        }

        callback = kwargs.pop('callback', None)
        if callback:
            mgmt_kwargs['callback'] = callback

        errback = kwargs.pop('errback', None)
        if errback:
            mgmt_kwargs['errback'] = errback

        if final_args.get("timeout", None) is not None:
            mgmt_kwargs["timeout"] = final_args.get("timeout")

        return management_operation(**mgmt_kwargs)

    def drop_index(self,
                   index_name,  # type: str
                   *options,   # type: DropSearchIndexOptions
                   **kwargs    # type: Dict[str, Any]
                   ) -> None:

        if is_null_or_empty(index_name):
            raise InvalidArgumentException("expected an index_name")

        final_args = forward_args(kwargs, *options)
        op_args = {
            'index_name': index_name
        }

        if final_args.get("client_context_id", None) is not None:
            op_args["client_context_id"] = final_args.get("client_context_id")

        mgmt_kwargs = {
            "conn": self._connection,
            "mgmt_op": mgmt_operations.SEARCH_INDEX.value,
            "op_type": search_index_mgmt_operations.DROP_INDEX.value,
            "op_args": op_args
        }

        callback = kwargs.pop('callback', None)
        if callback:
            mgmt_kwargs['callback'] = callback

        errback = kwargs.pop('errback', None)
        if errback:
            mgmt_kwargs['errback'] = errback

        if final_args.get("timeout", None) is not None:
            mgmt_kwargs["timeout"] = final_args.get("timeout")

        return management_operation(**mgmt_kwargs)

    def get_index(self,
                  index_name,  # type: str
                  *options,   # type: GetSearchIndexOptions
                  **kwargs    # type:  Dict[str, Any]
                  ) -> Optional[SearchIndex]:

        if is_null_or_empty(index_name):
            raise InvalidArgumentException(
                "expected index_name to not be empty")

        final_args = forward_args(kwargs, *options)
        op_args = {
            'index_name': index_name
        }

        if final_args.get("client_context_id", None) is not None:
            op_args["client_context_id"] = final_args.get("client_context_id")

        mgmt_kwargs = {
            "conn": self._connection,
            "mgmt_op": mgmt_operations.SEARCH_INDEX.value,
            "op_type": search_index_mgmt_operations.GET_INDEX.value,
            "op_args": op_args
        }

        callback = kwargs.pop('callback', None)
        if callback:
            mgmt_kwargs['callback'] = callback

        errback = kwargs.pop('errback', None)
        if errback:
            mgmt_kwargs['errback'] = errback

        if final_args.get("timeout", None) is not None:
            mgmt_kwargs["timeout"] = final_args.get("timeout")

        return management_operation(**mgmt_kwargs)

    def get_all_indexes(self,
                        *options,  # type: GetAllSearchIndexesOptions
                        **kwargs  # type: Dict[str, Any]
                        ) -> Optional[Iterable[SearchIndex]]:

        final_args = forward_args(kwargs, *options)
        op_args = {}

        if final_args.get("client_context_id", None) is not None:
            op_args["client_context_id"] = final_args.get("client_context_id")

        mgmt_kwargs = {
            "conn": self._connection,
            "mgmt_op": mgmt_operations.SEARCH_INDEX.value,
            "op_type": search_index_mgmt_operations.GET_ALL_INDEXES.value,
            "op_args": op_args
        }

        callback = kwargs.pop('callback', None)
        if callback:
            mgmt_kwargs['callback'] = callback

        errback = kwargs.pop('errback', None)
        if errback:
            mgmt_kwargs['errback'] = errback

        if final_args.get("timeout", None) is not None:
            mgmt_kwargs["timeout"] = final_args.get("timeout")

        return management_operation(**mgmt_kwargs)

    def get_indexed_documents_count(self,
                                    index_name,  # type: str
                                    *options,   # type: GetSearchIndexedDocumentsCountOptions
                                    **kwargs    # type: Dict[str, Any]
                                    ) -> Optional[int]:

        if is_null_or_empty(index_name):
            raise InvalidArgumentException(
                "expected index_name to not be empty")

        final_args = forward_args(kwargs, *options)
        op_args = {
            'index_name': index_name
        }

        if final_args.get("client_context_id", None) is not None:
            op_args["client_context_id"] = final_args.get("client_context_id")

        mgmt_kwargs = {
            "conn": self._connection,
            "mgmt_op": mgmt_operations.SEARCH_INDEX.value,
            "op_type": search_index_mgmt_operations.GET_INDEX_DOCUMENT_COUNT.value,
            "op_args": op_args
        }

        callback = kwargs.pop('callback', None)
        if callback:
            mgmt_kwargs['callback'] = callback

        errback = kwargs.pop('errback', None)
        if errback:
            mgmt_kwargs['errback'] = errback

        if final_args.get("timeout", None) is not None:
            mgmt_kwargs["timeout"] = final_args.get("timeout")

        return management_operation(**mgmt_kwargs)

    def pause_ingest(self,
                     index_name,  # type: str
                     *options,  # type: PauseIngestSearchIndexOptions
                     **kwargs  # type: Dict[str, Any]
                     ) -> None:

        if is_null_or_empty(index_name):
            raise InvalidArgumentException(
                "expected index_name to not be empty")

        final_args = forward_args(kwargs, *options)
        op_args = {
            'index_name': index_name,
            'pause': True
        }

        if final_args.get("client_context_id", None) is not None:
            op_args["client_context_id"] = final_args.get("client_context_id")

        mgmt_kwargs = {
            "conn": self._connection,
            "mgmt_op": mgmt_operations.SEARCH_INDEX.value,
            "op_type": search_index_mgmt_operations.CONTROL_INGEST.value,
            "op_args": op_args
        }

        callback = kwargs.pop('callback', None)
        if callback:
            mgmt_kwargs['callback'] = callback

        errback = kwargs.pop('errback', None)
        if errback:
            mgmt_kwargs['errback'] = errback

        if final_args.get("timeout", None) is not None:
            mgmt_kwargs["timeout"] = final_args.get("timeout")

        return management_operation(**mgmt_kwargs)

    def resume_ingest(self,
                      index_name,  # type: str
                      *options,  # type: ResumeIngestSearchIndexOptions
                      **kwargs  # type: Dict[str, Any]
                      ) -> None:

        if is_null_or_empty(index_name):
            raise InvalidArgumentException(
                "expected index_name to not be empty")

        final_args = forward_args(kwargs, *options)
        op_args = {
            'index_name': index_name,
            'pause': False
        }

        if final_args.get("client_context_id", None) is not None:
            op_args["client_context_id"] = final_args.get("client_context_id")

        mgmt_kwargs = {
            "conn": self._connection,
            "mgmt_op": mgmt_operations.SEARCH_INDEX.value,
            "op_type": search_index_mgmt_operations.CONTROL_INGEST.value,
            "op_args": op_args
        }

        callback = kwargs.pop('callback', None)
        if callback:
            mgmt_kwargs['callback'] = callback

        errback = kwargs.pop('errback', None)
        if errback:
            mgmt_kwargs['errback'] = errback

        if final_args.get("timeout", None) is not None:
            mgmt_kwargs["timeout"] = final_args.get("timeout")

        return management_operation(**mgmt_kwargs)

    def allow_querying(self,
                       index_name,  # type: str
                       *options,  # type: AllowQueryingSearchIndexOptions
                       **kwargs  # type: Dict[str, Any]
                       ) -> None:

        if is_null_or_empty(index_name):
            raise InvalidArgumentException(
                "expected index_name to not be empty")

        final_args = forward_args(kwargs, *options)
        op_args = {
            'index_name': index_name,
            'allow': True
        }

        if final_args.get("client_context_id", None) is not None:
            op_args["client_context_id"] = final_args.get("client_context_id")

        mgmt_kwargs = {
            "conn": self._connection,
            "mgmt_op": mgmt_operations.SEARCH_INDEX.value,
            "op_type": search_index_mgmt_operations.CONTROL_QUERY.value,
            "op_args": op_args
        }

        callback = kwargs.pop('callback', None)
        if callback:
            mgmt_kwargs['callback'] = callback

        errback = kwargs.pop('errback', None)
        if errback:
            mgmt_kwargs['errback'] = errback

        if final_args.get("timeout", None) is not None:
            mgmt_kwargs["timeout"] = final_args.get("timeout")

        return management_operation(**mgmt_kwargs)

    def disallow_querying(self,
                          index_name,  # type: str
                          *options,  # type: DisallowQueryingSearchIndexOptions
                          **kwargs  # type: Dict[str, Any]
                          ) -> None:

        if is_null_or_empty(index_name):
            raise InvalidArgumentException(
                "expected index_name to not be empty")

        final_args = forward_args(kwargs, *options)
        op_args = {
            'index_name': index_name,
            'allow': False
        }

        if final_args.get("client_context_id", None) is not None:
            op_args["client_context_id"] = final_args.get("client_context_id")

        mgmt_kwargs = {
            "conn": self._connection,
            "mgmt_op": mgmt_operations.SEARCH_INDEX.value,
            "op_type": search_index_mgmt_operations.CONTROL_QUERY.value,
            "op_args": op_args
        }

        callback = kwargs.pop('callback', None)
        if callback:
            mgmt_kwargs['callback'] = callback

        errback = kwargs.pop('errback', None)
        if errback:
            mgmt_kwargs['errback'] = errback

        if final_args.get("timeout", None) is not None:
            mgmt_kwargs["timeout"] = final_args.get("timeout")

        return management_operation(**mgmt_kwargs)

    def freeze_plan(self,
                    index_name,  # type: str
                    *options,  # type: FreezePlanSearchIndexOptions
                    **kwargs  # type: Dict[str, Any]
                    ) -> None:

        if is_null_or_empty(index_name):
            raise InvalidArgumentException(
                "expected index_name to not be empty")

        final_args = forward_args(kwargs, *options)
        op_args = {
            'index_name': index_name,
            'freeze': True
        }

        if final_args.get("client_context_id", None) is not None:
            op_args["client_context_id"] = final_args.get("client_context_id")

        mgmt_kwargs = {
            "conn": self._connection,
            "mgmt_op": mgmt_operations.SEARCH_INDEX.value,
            "op_type": search_index_mgmt_operations.FREEZE_PLAN.value,
            "op_args": op_args
        }

        callback = kwargs.pop('callback', None)
        if callback:
            mgmt_kwargs['callback'] = callback

        errback = kwargs.pop('errback', None)
        if errback:
            mgmt_kwargs['errback'] = errback

        if final_args.get("timeout", None) is not None:
            mgmt_kwargs["timeout"] = final_args.get("timeout")

        return management_operation(**mgmt_kwargs)

    def unfreeze_plan(self,
                      index_name,  # type: str
                      *options,  # type: UnfreezePlanSearchIndexOptions
                      **kwargs  # type: Dict[str, Any]
                      ) -> None:

        if is_null_or_empty(index_name):
            raise InvalidArgumentException(
                "expected index_name to not be empty")

        final_args = forward_args(kwargs, *options)
        op_args = {
            'index_name': index_name,
            'freeze': False
        }

        if final_args.get("client_context_id", None) is not None:
            op_args["client_context_id"] = final_args.get("client_context_id")

        mgmt_kwargs = {
            "conn": self._connection,
            "mgmt_op": mgmt_operations.SEARCH_INDEX.value,
            "op_type": search_index_mgmt_operations.FREEZE_PLAN.value,
            "op_args": op_args
        }

        callback = kwargs.pop('callback', None)
        if callback:
            mgmt_kwargs['callback'] = callback

        errback = kwargs.pop('errback', None)
        if errback:
            mgmt_kwargs['errback'] = errback

        if final_args.get("timeout", None) is not None:
            mgmt_kwargs["timeout"] = final_args.get("timeout")

        return management_operation(**mgmt_kwargs)

    def analyze_document(self,   # noqa: C901
                         index_name,  # type: str
                         document,  # type: Any
                         *options,  # type: AnalyzeDocumentSearchIndexOptions
                         **kwargs  # type: Dict[str, Any]
                         ) -> Optional[Dict[str, Any]]:

        if is_null_or_empty(index_name):
            raise InvalidArgumentException("expected an index_name")
        if not document:
            raise InvalidArgumentException("expected a document to analyze")
        json_doc = None
        try:
            json_doc = json.dumps(document)
        except Exception:
            raise InvalidArgumentException(
                "cannot convert doc to json to analyze")

        final_args = forward_args(kwargs, *options)
        op_args = {
            'index_name': index_name,
            'encoded_document': json_doc
        }

        if final_args.get("client_context_id", None) is not None:
            op_args["client_context_id"] = final_args.get("client_context_id")

        mgmt_kwargs = {
            "conn": self._connection,
            "mgmt_op": mgmt_operations.SEARCH_INDEX.value,
            "op_type": search_index_mgmt_operations.ANALYZE_DOCUMENT.value,
            "op_args": op_args
        }

        callback = kwargs.pop('callback', None)
        if callback:
            mgmt_kwargs['callback'] = callback

        errback = kwargs.pop('errback', None)
        if errback:
            mgmt_kwargs['errback'] = errback

        if final_args.get("timeout", None) is not None:
            mgmt_kwargs["timeout"] = final_args.get("timeout")

        return management_operation(**mgmt_kwargs)

    def get_index_stats(self,
                        index_name,  # type: str
                        *options,  # type: GetSearchIndexStatsOptions
                        **kwargs  # type: Dict[str, Any]
                        ) -> Optional[Dict[str, Any]]:

        if is_null_or_empty(index_name):
            raise InvalidArgumentException("expected an index_name")

        final_args = forward_args(kwargs, *options)
        op_args = {
            'index_name': index_name
        }

        if final_args.get("client_context_id", None) is not None:
            op_args["client_context_id"] = final_args.get("client_context_id")

        mgmt_kwargs = {
            "conn": self._connection,
            "mgmt_op": mgmt_operations.SEARCH_INDEX.value,
            "op_type": search_index_mgmt_operations.GET_INDEX_STATS.value,
            "op_args": op_args
        }

        callback = kwargs.pop('callback', None)
        if callback:
            mgmt_kwargs['callback'] = callback

        errback = kwargs.pop('errback', None)
        if errback:
            mgmt_kwargs['errback'] = errback

        if final_args.get("timeout", None) is not None:
            mgmt_kwargs["timeout"] = final_args.get("timeout")

        return management_operation(**mgmt_kwargs)

    def get_all_index_stats(self,
                            *options,  # type: GetAllSearchIndexStatsOptions
                            **kwargs  # type: Dict[str, Any]
                            ) -> Optional[Dict[str, Any]]:

        final_args = forward_args(kwargs, *options)
        op_args = {}

        if final_args.get("client_context_id", None) is not None:
            op_args["client_context_id"] = final_args.get("client_context_id")

        mgmt_kwargs = {
            "conn": self._connection,
            "mgmt_op": mgmt_operations.SEARCH_INDEX.value,
            "op_type": search_index_mgmt_operations.GET_ALL_STATS.value,
            "op_args": op_args
        }

        callback = kwargs.pop('callback', None)
        if callback:
            mgmt_kwargs['callback'] = callback

        errback = kwargs.pop('errback', None)
        if errback:
            mgmt_kwargs['errback'] = errback

        if final_args.get("timeout", None) is not None:
            mgmt_kwargs["timeout"] = final_args.get("timeout")

        return management_operation(**mgmt_kwargs)


@dataclass
class SearchIndex:
    name: str
    source_type: str = 'couchbase'
    idx_type: str = 'fulltext-index'
    source_name: str = None
    uuid: str = None
    params: dict = field(default_factory=dict)
    source_uuid: str = None
    source_params: dict = field(default_factory=dict)
    plan_params: dict = field(default_factory=dict)

    def is_valid(self):
        return not (is_null_or_empty(self.name)
                    or is_null_or_empty(self.idx_type)
                    or is_null_or_empty(self.source_type))

    def as_dict(self):
        output = {
            'name': self.name,
            'type': self.idx_type,
            'source_type': self.source_type
        }
        if self.uuid:
            output['uuid'] = self.uuid
        if len(self.params) > 0:
            output['params_json'] = json.dumps(self.params)
        if self.source_uuid:
            output['source_uuid'] = self.source_uuid
        if self.source_name:
            output['source_name'] = self.source_name
        if len(self.source_params) > 0:
            output['source_params_json'] = json.dumps(self.source_params)
        if len(self.plan_params) > 0:
            output['plan_params_json'] = json.dumps(self.plan_params)
        return output

    @classmethod
    def from_server(cls,
                    json_data  # type: Dict[str, Any]
                    ):

        params = None
        if 'params_json' in json_data:
            params = json.loads(json_data.get('params_json'))

        source_params = None
        if 'source_params_json' in json_data:
            source_params = json.loads(json_data.get('source_params_json'))

        plan_params = None
        if 'plan_params_json' in json_data:
            plan_params = json.loads(json_data.get('plan_params_json'))

        return cls(json_data.get('name'),
                   json_data.get('type'),
                   json_data.get('source_type'),
                   json_data.get('source_name', None),
                   json_data.get('uuid', None),
                   params,
                   json_data.get('source_uuid', None),
                   source_params,
                   plan_params
                   )
