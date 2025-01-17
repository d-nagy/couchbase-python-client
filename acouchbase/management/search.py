from typing import (TYPE_CHECKING,
                    Any,
                    Awaitable,
                    Dict,
                    Iterable)

from acouchbase.management.logic.wrappers import AsyncMgmtWrapper
from couchbase.management.logic import ManagementType
from couchbase.management.logic.search_index_logic import SearchIndex, SearchIndexManagerLogic

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


class SearchIndexManager(SearchIndexManagerLogic):
    def __init__(self, connection, loop):
        super().__init__(connection)
        self._loop = loop

    @property
    def loop(self):
        """
        **INTERNAL**
        """
        return self._loop

    @AsyncMgmtWrapper.inject_callbacks(None, ManagementType.SearchIndexMgmt, SearchIndexManagerLogic._ERROR_MAPPING)
    def upsert_index(self,
                     index,     # type: SearchIndex
                     *options,  # type: UpsertSearchIndexOptions
                     **kwargs   # type: Dict[str, Any]
                     ) -> Awaitable[None]:

        super().upsert_index(index, *options, **kwargs)

    @AsyncMgmtWrapper.inject_callbacks(None, ManagementType.SearchIndexMgmt, SearchIndexManagerLogic._ERROR_MAPPING)
    def drop_index(self,
                   index_name,  # type: str
                   *options,   # type: DropSearchIndexOptions
                   **kwargs    # type: Dict[str, Any]
                   ) -> Awaitable[None]:

        super().drop_index(index_name, *options, **kwargs)

    @AsyncMgmtWrapper.inject_callbacks(SearchIndex, ManagementType.SearchIndexMgmt,
                                       SearchIndexManagerLogic._ERROR_MAPPING)
    def get_index(self,
                  index_name,  # type: str
                  *options,   # type: GetSearchIndexOptions
                  **kwargs    # type: Dict[str, Any]
                  ) -> Awaitable[SearchIndex]:

        super().get_index(index_name, *options, **kwargs)

    @AsyncMgmtWrapper.inject_callbacks(SearchIndex, ManagementType.SearchIndexMgmt,
                                       SearchIndexManagerLogic._ERROR_MAPPING)
    def get_all_indexes(self,
                        *options,  # type: GetAllSearchIndexesOptions
                        **kwargs  # type: Dict[str, Any]
                        ) -> Awaitable[Iterable[SearchIndex]]:
        super().get_all_indexes(*options, **kwargs)

    @AsyncMgmtWrapper.inject_callbacks(int, ManagementType.SearchIndexMgmt, SearchIndexManagerLogic._ERROR_MAPPING)
    def get_indexed_documents_count(self,
                                    index_name,  # type: str
                                    *options,   # type: GetSearchIndexedDocumentsCountOptions
                                    **kwargs    # type: Dict[str, Any]
                                    ) -> Awaitable[int]:
        super().get_indexed_documents_count(index_name, *options, **kwargs)

    @AsyncMgmtWrapper.inject_callbacks(None, ManagementType.SearchIndexMgmt, SearchIndexManagerLogic._ERROR_MAPPING)
    def pause_ingest(self,
                     index_name,  # type: str
                     *options,  # type: PauseIngestSearchIndexOptions
                     **kwargs  # type: Dict[str, Any]
                     ) -> Awaitable[None]:
        super().pause_ingest(index_name, *options, **kwargs)

    @AsyncMgmtWrapper.inject_callbacks(None, ManagementType.SearchIndexMgmt, SearchIndexManagerLogic._ERROR_MAPPING)
    def resume_ingest(self,
                      index_name,  # type: str
                      *options,  # type: ResumeIngestSearchIndexOptions
                      **kwargs  # type: Dict[str, Any]
                      ) -> Awaitable[None]:
        super().resume_ingest(index_name, *options, **kwargs)

    @AsyncMgmtWrapper.inject_callbacks(None, ManagementType.SearchIndexMgmt, SearchIndexManagerLogic._ERROR_MAPPING)
    def allow_querying(self,
                       index_name,  # type: str
                       *options,  # type: AllowQueryingSearchIndexOptions
                       **kwargs  # type: Dict[str, Any]
                       ) -> Awaitable[None]:
        super().allow_querying(index_name, *options, **kwargs)

    @AsyncMgmtWrapper.inject_callbacks(None, ManagementType.SearchIndexMgmt, SearchIndexManagerLogic._ERROR_MAPPING)
    def disallow_querying(self,
                          index_name,  # type: str
                          *options,  # type: DisallowQueryingSearchIndexOptions
                          **kwargs  # type: Dict[str, Any]
                          ) -> Awaitable[None]:
        super().disallow_querying(index_name, *options, **kwargs)

    @AsyncMgmtWrapper.inject_callbacks(None, ManagementType.SearchIndexMgmt, SearchIndexManagerLogic._ERROR_MAPPING)
    def freeze_plan(self,
                    index_name,  # type: str
                    *options,  # type: FreezePlanSearchIndexOptions
                    **kwargs  # type: Dict[str, Any]
                    ) -> Awaitable[None]:
        super().freeze_plan(index_name, *options, **kwargs)

    @AsyncMgmtWrapper.inject_callbacks(None, ManagementType.SearchIndexMgmt, SearchIndexManagerLogic._ERROR_MAPPING)
    def unfreeze_plan(self,
                      index_name,  # type: str
                      *options,  # type: UnfreezePlanSearchIndexOptions
                      **kwargs  # type: Dict[str, Any]
                      ) -> Awaitable[None]:
        super().unfreeze_plan(index_name, *options, **kwargs)

    @AsyncMgmtWrapper.inject_callbacks(dict, ManagementType.SearchIndexMgmt, SearchIndexManagerLogic._ERROR_MAPPING)
    def analyze_document(self,
                         index_name,  # type: str
                         document,  # type: Any
                         *options,  # type: AnalyzeDocumentSearchIndexOptions
                         **kwargs  # type: Dict[str, Any]
                         ) -> Awaitable[Dict[str, Any]]:
        super().analyze_document(index_name, document, *options, **kwargs)

    @AsyncMgmtWrapper.inject_callbacks(dict, ManagementType.SearchIndexMgmt, SearchIndexManagerLogic._ERROR_MAPPING)
    def get_index_stats(self,
                        index_name,  # type: str
                        *options,  # type: GetSearchIndexStatsOptions
                        **kwargs  # type: Dict[str, Any]
                        ) -> Awaitable[Dict[str, Any]]:
        super().get_index_stats(index_name, *options, **kwargs)

    @AsyncMgmtWrapper.inject_callbacks(dict, ManagementType.SearchIndexMgmt, SearchIndexManagerLogic._ERROR_MAPPING)
    def get_all_index_stats(self,
                            *options,  # type: GetAllSearchIndexStatsOptions
                            **kwargs  # type: Dict[str, Any]
                            ) -> Awaitable[Dict[str, Any]]:
        super().get_all_index_stats(*options, **kwargs)
