import asyncio
import json
import pathlib
from datetime import timedelta
from os import path
from typing import (List,
                    Optional,
                    Union)

import pytest
import pytest_asyncio

import couchbase.search as search
from acouchbase.cluster import Cluster
from couchbase.auth import PasswordAuthenticator
from couchbase.exceptions import InvalidArgumentException, SearchIndexNotFoundException
from couchbase.management.search import SearchIndex
from couchbase.mutation_state import MutationState
from couchbase.options import ClusterOptions
from couchbase.result import MutationToken, SearchResult
from couchbase.search import (HighlightStyle,
                              MatchOperator,
                              SearchDateRangeFacet,
                              SearchFacetResult,
                              SearchNumericRangeFacet,
                              SearchOptions,
                              SearchRow,
                              SearchTermFacet)

from ._test_utils import TestEnvironment


class SearchTests:
    TEST_INDEX_NAME = 'test-search-index'
    TEST_INDEX_PATH = path.join(pathlib.Path(__file__).parent.parent.parent,
                                'tests',
                                'test_cases',
                                f'{TEST_INDEX_NAME}-params.json')

    @pytest_asyncio.fixture(scope="class")
    def event_loop(self):
        loop = asyncio.get_event_loop()
        yield loop
        loop.close()

    @pytest_asyncio.fixture(scope="class", name="cb_env")
    async def couchbase_test_environment(self, couchbase_config):
        conn_string = couchbase_config.get_connection_string()
        username, pw = couchbase_config.get_username_and_pw()
        opts = ClusterOptions(PasswordAuthenticator(username, pw))
        cluster = Cluster(
            conn_string, opts)
        await cluster.on_connect()
        await cluster.cluster_info()
        bucket = cluster.bucket(f"{couchbase_config.bucket_name}")
        await cluster.on_connect()

        coll = bucket.default_collection()
        cb_env = TestEnvironment(cluster,
                                 bucket,
                                 coll,
                                 couchbase_config,
                                 manage_buckets=True,
                                 manage_search_indexes=True)

        await cb_env.load_data()
        await self._load_search_index(cb_env)
        yield cb_env
        await cb_env.purge_data()
        await self._drop_search_index(cb_env)
        await cluster.close()

    async def _load_search_index(self, cb_env):
        with open(self.TEST_INDEX_PATH) as params_file:
            input = params_file.read()
            params_json = json.loads(input)
            try:
                await cb_env.sixm.get_index(self.TEST_INDEX_NAME)
                # wait at least 5 minutes
                await self._check_indexed_docs(cb_env, retries=30, delay=10)
            except Exception:
                await cb_env.sixm.upsert_index(
                    SearchIndex(name=self.TEST_INDEX_NAME,
                                idx_type='fulltext-index',
                                source_name='default',
                                source_type='couchbase',
                                params=params_json)
                )
                # make sure the index loads...
                await self._check_indexed_docs(cb_env, retries=30, delay=10)

    async def _check_indexed_docs(self, cb_env, retries=20, delay=30, num_docs=20, idx='test-search-index'):
        indexed_docs = 0
        no_docs_cutoff = 300
        for i in range(retries):
            # if no docs after waiting for a period of time, exit
            if indexed_docs == 0 and i * delay >= no_docs_cutoff:
                return 0
            indexed_docs = await cb_env.try_n_times(
                10, 10, cb_env.sixm.get_indexed_documents_count, idx)
            if indexed_docs >= num_docs:
                break
            print(f'Found {indexed_docs} indexed docs, waiting a bit...')
            await asyncio.sleep(delay)

        return indexed_docs

    @pytest.fixture(scope="class")
    def check_disable_scoring_supported(self, cb_env):
        cb_env.check_if_feature_supported('search_disable_scoring')

    async def _drop_search_index(self, cb_env):
        try:
            await cb_env.sixm.drop_index(self.TEST_INDEX_NAME)
        except SearchIndexNotFoundException:
            pass
        except Exception as ex:
            raise ex

    async def assert_rows(self,
                          result,  # type: SearchResult
                          expected_count,  # type: int
                          return_rows=False  # type: bool
                          ) -> Optional[List[Union[SearchRow, dict]]]:
        rows = []
        assert isinstance(result, SearchResult)
        async for row in result.rows():
            assert row is not None
            rows.append(row)
        assert len(rows) >= expected_count

        if return_rows is True:
            return rows

    @pytest.mark.asyncio
    async def test_cluster_search(self, cb_env):
        q = search.TermQuery('home')
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10))
        await self.assert_rows(res, 2)

    @pytest.mark.asyncio
    async def test_cluster_search_fields(self, cb_env):
        test_fields = ['name', 'activity']
        q = search.TermQuery('home')
        # verify fields works w/in kwargs
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10), fields=test_fields)

        rows = await self.assert_rows(res, 1, return_rows=True)
        first_entry = rows[0]
        assert isinstance(first_entry, SearchRow)
        assert isinstance(first_entry.fields, dict)
        assert first_entry.fields != {}
        res = list(map(lambda f: f in test_fields, first_entry.fields.keys()))
        assert all(map(lambda f: f in test_fields, first_entry.fields.keys())) is True

        # verify fields works w/in options
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10, fields=test_fields))

        rows = await self.assert_rows(res, 1, return_rows=True)
        first_entry = rows[0]
        assert isinstance(first_entry, SearchRow)
        assert isinstance(first_entry.fields, dict)
        assert first_entry.fields != {}
        res = list(map(lambda f: f in test_fields, first_entry.fields.keys()))
        assert all(map(lambda f: f in test_fields, first_entry.fields.keys())) is True

    # @TODO: 3.x raises a SearchException...
    def test_cluster_search_facets_fail(self, cb_env):
        q = search.TermQuery('home')
        with pytest.raises(ValueError):
            cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10, facets={'test-facet': None}))

    @pytest.mark.asyncio
    async def test_cluster_search_top_level_facets(self, cb_env):
        # if the facet limit is omitted, the details of the facets will not be provided
        # (i.e. SearchFacetResult.terms is None,
        #       SearchFacetResult.numeric_ranges is None and SearchFacetResult.date_ranges is None)
        facet_name = 'activity'
        facet = search.TermFacet('activity')
        q = search.TermQuery('home')
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10, facets={facet_name: facet}))

        await self.assert_rows(res, 1)
        facets = res.facets()
        assert isinstance(facets, dict)
        result_facet = facets[facet_name]
        assert isinstance(result_facet, SearchFacetResult)
        assert result_facet.name == facet_name
        assert result_facet.field == facet_name
        assert result_facet.terms is None
        assert result_facet.numeric_ranges is None
        assert result_facet.date_ranges is None

        facet_name = 'rating'
        facet = search.NumericFacet('rating')
        facet.add_range('low', max=2)
        facet.add_range('med', min=2, max=4)
        facet.add_range('high', min=4)
        q = search.TermQuery('home')
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10, facets={facet_name: facet}))

        await self.assert_rows(res, 1)
        facets = res.facets()
        assert isinstance(facets, dict)
        result_facet = facets[facet_name]
        assert isinstance(result_facet, SearchFacetResult)
        assert result_facet.name == facet_name
        assert result_facet.field == facet_name
        assert result_facet.terms is None
        assert result_facet.numeric_ranges is None
        assert result_facet.date_ranges is None

    @pytest.mark.asyncio
    async def test_cluster_search_top_level_facets_kwargs(self, cb_env):
        # if the facet limit is omitted, the details of the facets will not be provided
        # (i.e. SearchFacetResult.terms is None,
        #       SearchFacetResult.numeric_ranges is None and SearchFacetResult.date_ranges is None)
        facet_name = 'activity'
        facet = search.TermFacet('activity')
        q = search.TermQuery('home')
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10), facets={facet_name: facet})

        await self.assert_rows(res, 1)
        facets = res.facets()
        assert isinstance(facets, dict)
        result_facet = facets[facet_name]
        assert isinstance(result_facet, SearchFacetResult)
        assert result_facet.name == facet_name
        assert result_facet.field == facet_name
        assert result_facet.terms is None
        assert result_facet.numeric_ranges is None
        assert result_facet.date_ranges is None

        facet_name = 'rating'
        facet = search.NumericFacet('rating')
        facet.add_range('low', max=2)
        facet.add_range('med', min=2, max=4)
        facet.add_range('high', min=4)
        q = search.TermQuery('home')
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10), facets={facet_name: facet})

        await self.assert_rows(res, 1)
        facets = res.facets()
        assert isinstance(facets, dict)
        result_facet = facets[facet_name]
        assert isinstance(result_facet, SearchFacetResult)
        assert result_facet.name == facet_name
        assert result_facet.field == facet_name
        assert result_facet.terms is None
        assert result_facet.numeric_ranges is None
        assert result_facet.date_ranges is None

    @pytest.mark.asyncio
    async def test_cluster_search_term_facets(self, cb_env):

        facet_name = 'activity'
        facet = search.TermFacet('activity', 5)
        q = search.TermQuery('home')
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10, facets={facet_name: facet}))

        await self.assert_rows(res, 1)
        facets = res.facets()
        assert isinstance(facets, dict)
        result_facet = facets[facet_name]
        assert isinstance(result_facet, SearchFacetResult)
        assert result_facet.name == facet_name
        assert result_facet.field == facet_name
        assert all(map(lambda ft: isinstance(ft, SearchTermFacet), result_facet.terms)) is True
        assert len(result_facet.terms) <= facet.limit

    @pytest.mark.asyncio
    async def test_cluster_search_numeric_facets(self, cb_env):

        facet_name = 'rating'
        facet = search.NumericFacet('rating', limit=3)
        facet.add_range('low', max=2)
        facet.add_range('med', min=2, max=4)
        facet.add_range('high', min=4)
        q = search.TermQuery('home')
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10, facets={facet_name: facet}))

        await self.assert_rows(res, 1)
        facets = res.facets()
        assert isinstance(facets, dict)
        result_facet = facets[facet_name]
        assert isinstance(result_facet, SearchFacetResult)
        assert result_facet.name == facet_name
        assert result_facet.field == facet_name
        assert all(map(lambda ft: isinstance(ft, SearchNumericRangeFacet), result_facet.numeric_ranges)) is True
        assert len(result_facet.numeric_ranges) <= facet.limit

    @pytest.mark.asyncio
    async def test_cluster_search_date_facets(self, cb_env):
        facet_name = 'updated'
        facet = search.DateFacet('updated', limit=3)
        facet.add_range('early', end='2022-02-02T00:00:00Z')
        facet.add_range('mid', start='2022-02-03T00:00:00Z',
                        end='2022-03-03T00:00:00Z')
        facet.add_range('late', start='2022-03-04T00:00:00Z')
        q = search.TermQuery('home')
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10, facets={facet_name: facet}))

        await self.assert_rows(res, 1)
        facets = res.facets()
        assert isinstance(facets, dict)
        result_facet = facets[facet_name]
        assert isinstance(result_facet, SearchFacetResult)
        assert result_facet.name == facet_name
        assert result_facet.field == facet_name
        assert all(map(lambda ft: isinstance(ft, SearchDateRangeFacet), result_facet.date_ranges)) is True
        assert len(result_facet.date_ranges) <= facet.limit

    @pytest.mark.usefixtures('check_disable_scoring_supported')
    @pytest.mark.asyncio
    async def test_cluster_search_disable_scoring(self, cb_env):

        # verify disable scoring works w/in SearchOptions
        q = search.TermQuery('home')
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10, disable_scoring=True))
        rows = await self.assert_rows(res, 1, return_rows=True)
        assert all(map(lambda r: r.score == 0, rows)) is True

        # verify disable scoring works w/in kwargs
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10), disable_scoring=True)
        rows = await self.assert_rows(res, 1, return_rows=True)
        assert all(map(lambda r: r.score == 0, rows)) is True

        # verify setting disable_scoring to False works
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10, disable_scoring=False))
        rows = await self.assert_rows(res, 1, return_rows=True)
        assert all(map(lambda r: r.score != 0, rows)) is True

        # verify default disable_scoring is False
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10))
        rows = await self.assert_rows(res, 1, return_rows=True)
        assert all(map(lambda r: r.score != 0, rows)) is True

    @pytest.mark.asyncio
    async def test_cluster_search_highlight(self, cb_env):

        q = search.TermQuery('home')
        # check w/in options
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10, highlight_style=HighlightStyle.Html))
        rows = await self.assert_rows(res, 1, return_rows=True)
        locations = rows[0].locations
        fragments = rows[0].fragments
        assert isinstance(locations, search.SearchRowLocations)
        assert isinstance(fragments, dict)
        assert all(map(lambda l: isinstance(l, search.SearchRowLocation), locations.get_all())) is True

        # check w/in options
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10), highlight_style=HighlightStyle.Html)
        rows = await self.assert_rows(res, 1, return_rows=True)
        locations = rows[0].locations
        fragments = rows[0].fragments
        assert isinstance(locations, search.SearchRowLocations)
        assert isinstance(fragments, dict)
        assert all(map(lambda l: isinstance(l, search.SearchRowLocation), locations.get_all())) is True

    # @TODO(PYCBC-1296):  DIFF between 3.x and 4.x, locations returns None
    @pytest.mark.asyncio
    async def test_search_no_include_locations(self, cb_env):
        q = search.TermQuery('home')
        # check w/in options
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10, include_locations=False))
        rows = await self.assert_rows(res, 1, return_rows=True)
        locations = rows[0].locations
        assert locations is None

        # check w/in kwargs
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10), include_locations=False)
        rows = await self.assert_rows(res, 1, return_rows=True)
        locations = rows[0].locations
        assert locations is None

    @pytest.mark.asyncio
    async def test_search_include_locations(self, cb_env):
        q = search.TermQuery('home')
        # check w/in options
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10, include_locations=True))
        rows = await self.assert_rows(res, 1, return_rows=True)
        locations = rows[0].locations
        assert isinstance(locations, search.SearchRowLocations)
        assert all(map(lambda l: isinstance(l, search.SearchRowLocation), locations.get_all())) is True

        # check w/in kwargs
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10), include_locations=True)
        rows = await self.assert_rows(res, 1, return_rows=True)
        locations = rows[0].locations
        assert isinstance(locations, search.SearchRowLocations)
        assert all(map(lambda l: isinstance(l, search.SearchRowLocation), locations.get_all())) is True

    @pytest.mark.asyncio
    async def test_cluster_search_scan_consistency(self, cb_env):
        q = search.TermQuery('home')
        # check w/in options
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10, scan_consistency=search.SearchScanConsistency.NOT_BOUNDED))
        await self.assert_rows(res, 1)

        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10, scan_consistency=search.SearchScanConsistency.REQUEST_PLUS))
        await self.assert_rows(res, 1)

        with pytest.raises(InvalidArgumentException):
            cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
                limit=10, scan_consistency=search.SearchScanConsistency.AT_PLUS))

    @pytest.mark.parametrize('operator, query_terms, expect_rows',
                             [(search.MatchOperator.AND, "home hollywood", True),
                              (search.MatchOperator.AND, "home :random:", False),
                              (search.MatchOperator.OR, "home hollywood", True),
                              (search.MatchOperator.OR, "home :random:", True)])
    @pytest.mark.asyncio
    async def test_search_match_operator(self, cb_env, operator, query_terms, expect_rows):
        import random
        import string

        random_query_term = "".join(random.choice(string.ascii_letters)
                                    for _ in range(10))

        if ':random:' in query_terms:
            query_terms.replace(':random:', random_query_term)

        q = search.MatchQuery(query_terms, match_operator=operator)

        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, limit=10)
        rows = await self.assert_rows(res, 0, return_rows=True)

        if expect_rows:
            assert len(rows) > 0
        else:
            assert len(rows) == 0

    @pytest.mark.asyncio
    async def test_search_match_operator_fail(self, cb_env):
        with pytest.raises(ValueError):
            q = search.MatchQuery('home hollywood', match_operator='NOT')
            cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, limit=10)

    @pytest.mark.asyncio
    async def test_search_raw_query(self, cb_env):
        query_args = {"match": "home hollywood",
                      "fuzziness": 2, "operator": "and"}
        q = search.RawQuery(query_args)
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, limit=10)
        await self.assert_rows(res, 1)

    # @TODO:  couchbase++ doesn't seem to do the raw sort correctly
    @pytest.mark.asyncio
    async def test_cluster_sort_str(self, cb_env):
        q = search.TermQuery('home')
        # score - ascending
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10, sort=['_score']))
        _ = await self.assert_rows(res, 1, return_rows=True)
        # print(rows)
        # score = rows[0].score
        # for row in rows[1:]:
        #     assert row.score >= score
        #     score = row.score

        # score - descending
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10, sort=['-_score']))
        _ = await self.assert_rows(res, 1, return_rows=True)
        # print(rows)
        # score = rows[0].score
        # for row in rows[1:]:
        #     assert score >= row.score
        #     score = row.score

    @pytest.mark.asyncio
    async def test_cluster_sort_score(self, cb_env):
        q = search.TermQuery('home')
        # score - ascending
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10, sort=[search.SortScore()]))
        rows = await self.assert_rows(res, 1, return_rows=True)

        score = rows[0].score
        for row in rows[1:]:
            assert row.score >= score
            score = row.score

        # score - descending
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10, sort=[search.SortScore(desc=True)]))
        rows = await self.assert_rows(res, 1, return_rows=True)

        score = rows[0].score
        for row in rows[1:]:
            assert score >= row.score
            score = row.score

    @pytest.mark.asyncio
    async def test_cluster_sort_id(self, cb_env):
        q = search.TermQuery('home')
        # score - ascending
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10, sort=[search.SortID()]))
        rows = await self.assert_rows(res, 1, return_rows=True)

        id = rows[0].id
        for row in rows[1:]:
            assert row.id >= id
            id = row.id

        # score - descending
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10, sort=[search.SortID(desc=True)]))
        rows = await self.assert_rows(res, 1, return_rows=True)

        id = rows[0].id
        for row in rows[1:]:
            assert id >= row.id
            id = row.id

    @pytest.mark.asyncio
    async def test_cluster_sort_field(self, cb_env):
        sort_field = "rating"
        q = search.TermQuery('home')
        # field - ascending
        sort = search.SortField(field=sort_field, type="number", mode="min", missing="last")
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10, sort=[sort], fields=[sort_field]))

        rows = await self.assert_rows(res, 1, return_rows=True)
        rating = rows[0].fields[sort_field]
        for row in rows[1:]:
            assert row.fields[sort_field] >= rating
            rating = row.fields[sort_field]

        # field - descending
        sort.desc = True
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10, sort=[sort], fields=[sort_field]))

        rows = await self.assert_rows(res, 1, return_rows=True)
        rating = rows[0].fields[sort_field]
        for row in rows[1:]:
            assert rating >= row.fields[sort_field]
            rating = row.fields[sort_field]

    @pytest.mark.asyncio
    async def test_cluster_sort_geo(self, cb_env):
        # @TODO:  better confirmation on results?
        sort_field = "geo"
        q = search.TermQuery('home')
        # geo - ascending
        sort = search.SortGeoDistance(field=sort_field, location=(37.7749, 122.4194), unit="meters")
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10, sort=[sort], fields=[sort_field]))
        await self.assert_rows(res, 1)

        # geo - descending
        sort.desc = True
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10, sort=[sort], fields=[sort_field]))
        await self.assert_rows(res, 1)

    @pytest.mark.asyncio
    async def test_cluster_sort_field_multi(self, cb_env):
        sort_fields = [
            search.SortField(field="rating", type="number",
                             mode="min", missing="last"),
            search.SortField(field="updated", type="number",
                             mode="min", missing="last"),
            search.SortScore(),
        ]
        sort_field_names = ["rating", "updated"]
        q = search.TermQuery('home')
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10, sort=sort_fields, fields=sort_field_names))
        await self.assert_rows(res, 1)

        sort_fields = [
            search.SortField(field="rating", type="number",
                             mode="min", missing="last", desc=True),
            search.SortField(field="updated", type="number",
                             mode="min", missing="last"),
            search.SortScore(desc=True),
        ]
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10, sort=sort_fields, fields=sort_field_names))
        await self.assert_rows(res, 1)

        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10, sort=["abv", "udpated", "-_score"]))
        await self.assert_rows(res, 1)


class SearchCollectionTests:
    TEST_INDEX_NAME = 'test-search-coll-index'
    TEST_INDEX_PATH = path.join(pathlib.Path(__file__).parent.parent.parent,
                                'tests',
                                'test_cases',
                                f'{TEST_INDEX_NAME}-params.json')

    @pytest_asyncio.fixture(scope="class")
    def event_loop(self):
        loop = asyncio.get_event_loop()
        yield loop
        loop.close()

    @pytest_asyncio.fixture(scope="class", name="cb_env")
    async def couchbase_test_environment(self, couchbase_config):
        conn_string = couchbase_config.get_connection_string()
        username, pw = couchbase_config.get_username_and_pw()
        opts = ClusterOptions(PasswordAuthenticator(username, pw))
        cluster = Cluster(
            conn_string, opts)
        await cluster.on_connect()
        await cluster.cluster_info()
        bucket = cluster.bucket(f"{couchbase_config.bucket_name}")
        await cluster.on_connect()

        coll = bucket.default_collection()
        cb_env = TestEnvironment(cluster,
                                 bucket,
                                 coll,
                                 couchbase_config,
                                 manage_buckets=True,
                                 manage_collections=True,
                                 manage_search_indexes=True)
        await cb_env.setup_named_collections()

        await cb_env.load_data()
        await self._load_search_index(cb_env)
        yield cb_env
        await cb_env.purge_data()
        await cb_env.teardown_named_collections()
        await self._drop_search_index(cb_env)
        await cluster.close()

    async def _load_search_index(self, cb_env):
        with open(self.TEST_INDEX_PATH) as params_file:
            input = params_file.read()
            params_json = json.loads(input)
            try:
                await cb_env.sixm.get_index(self.TEST_INDEX_NAME)
                # wait at least 5 minutes
                await self._check_indexed_docs(cb_env, retries=30, delay=10)
            except Exception:
                await cb_env.sixm.upsert_index(
                    SearchIndex(name=self.TEST_INDEX_NAME,
                                idx_type='fulltext-index',
                                source_name='default',
                                source_type='couchbase',
                                params=params_json)
                )
                # make sure the index loads...
                await self._check_indexed_docs(cb_env, retries=30, delay=10)

    async def _check_indexed_docs(self, cb_env, retries=20, delay=30, num_docs=20, idx='test-search-coll-index'):
        indexed_docs = 0
        no_docs_cutoff = 300
        for i in range(retries):
            # if no docs after waiting for a period of time, exit
            if indexed_docs == 0 and i * delay >= no_docs_cutoff:
                return 0
            indexed_docs = await cb_env.try_n_times(
                10, 10, cb_env.sixm.get_indexed_documents_count, idx)
            if indexed_docs >= num_docs:
                break
            print(f'Found {indexed_docs} indexed docs, waiting a bit...')
            await asyncio.sleep(delay)

        return indexed_docs

    async def _drop_search_index(self, cb_env):
        try:
            await cb_env.sixm.drop_index(self.TEST_INDEX_NAME)
        except SearchIndexNotFoundException:
            pass
        except Exception as ex:
            raise ex

    async def assert_rows(self,
                          result,  # type: SearchResult
                          expected_count,  # type: int
                          return_rows=False  # type: bool
                          ) -> Optional[List[Union[SearchRow, dict]]]:
        rows = []
        assert isinstance(result, SearchResult)
        async for row in result.rows():
            assert row is not None
            rows.append(row)
        assert len(rows) >= expected_count

        if return_rows is True:
            return rows

    # @TODO:  maybe need multiple collections...
    @pytest.mark.asyncio
    async def test_cluster_query_collections(self, cb_env):
        q = search.TermQuery('home')
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10, scope_name=cb_env.scope.name, collections=[cb_env.collection.name]))
        _ = await self.assert_rows(res, 2, return_rows=True)

        # rows = x.rows()
        # collections = list(map(lambda r: r.fields['_$c'], rows))
        # self.assertTrue(all([c for c in collections if c == 'breweries']))
        # SearchResultTest._check_search_result(self, initial, 1, x)

    @pytest.mark.asyncio
    async def test_scope_query_collections(self, cb_env):
        q = search.TermQuery('home')
        res = cb_env.scope.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10, collections=[cb_env.collection.name]))
        await self.assert_rows(res, 2)


class SearchStringTests:
    IDX_NAME = 'test-idx'

    def get_encoded_query(self, search_query):
        encoded_q = search_query.as_encodable()
        encoded_q['query'] = json.loads(encoded_q['query'])
        if 'facets' in encoded_q:
            encoded_q['facets'] = json.loads(encoded_q['facets'])
        if 'sort_specs' in encoded_q:
            encoded_q['sort'] = json.loads(encoded_q['sort_specs'])

        return encoded_q

    def test_params(self):
        q = search.TermQuery('someterm')
        # no opts - metrics will default to True
        opts = SearchOptions()
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q, opts
        )
        base_opts = {'metrics': True}
        assert search_query.params == base_opts

        # limit
        opts = SearchOptions(limit=10)
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q, opts
        )
        exp_opts = base_opts.copy()
        exp_opts['limit'] = 10
        assert search_query.params == exp_opts

        # skip
        opts = SearchOptions(skip=10)
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q, opts
        )
        exp_opts = base_opts.copy()
        exp_opts['skip'] = 10
        assert search_query.params == exp_opts

        # explain
        opts = SearchOptions(explain=True)
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q, opts
        )
        exp_opts = base_opts.copy()
        exp_opts['explain'] = True
        assert search_query.params == exp_opts

        # include_locations
        opts = SearchOptions(include_locations=True)
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q, opts
        )
        exp_opts = base_opts.copy()
        exp_opts['include_locations'] = True
        assert search_query.params == exp_opts

        # disable_scoring
        opts = SearchOptions(disable_scoring=True)
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q, opts
        )
        exp_opts = base_opts.copy()
        exp_opts['disable_scoring'] = True
        assert search_query.params == exp_opts

        # highlight_style
        opts = SearchOptions(highlight_style=HighlightStyle.Html)
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q, opts
        )
        exp_opts = base_opts.copy()
        exp_opts['highlight_style'] = HighlightStyle.Html.value
        assert search_query.params == exp_opts

        # highlight_style + highlight_fields
        opts = SearchOptions(highlight_style=HighlightStyle.Ansi, highlight_fields=['foo', 'bar', 'baz'])
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q, opts
        )
        exp_opts = base_opts.copy()
        exp_opts['highlight_style'] = HighlightStyle.Ansi.value
        exp_opts['highlight_fields'] = ['foo', 'bar', 'baz']
        assert search_query.params == exp_opts

        # fields
        opts = SearchOptions(fields=['foo', 'bar', 'baz'])
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q, opts
        )
        exp_opts = base_opts.copy()
        exp_opts['fields'] = ['foo', 'bar', 'baz']
        assert search_query.params == exp_opts

        # sort
        opts = SearchOptions(sort=['f1', 'f2', '-_score'])
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q, opts
        )
        exp_opts = base_opts.copy()
        exp_opts['sort'] = ['f1', 'f2', '-_score']
        params = search_query.params
        params['sort'] = search_query.sort
        assert params == exp_opts

        # scan_consistency
        opts = SearchOptions(scan_consistency=search.SearchScanConsistency.REQUEST_PLUS)
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q, opts
        )
        exp_opts = base_opts.copy()
        exp_opts['scan_consistency'] = search.SearchScanConsistency.REQUEST_PLUS.value
        assert search_query.params == exp_opts

        # scope/collections
        opts = SearchOptions(scope_name='test-scope', collections=['test-collection-1', 'test-collection-2'])
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q, opts
        )
        exp_opts = base_opts.copy()
        exp_opts['scope_name'] = 'test-scope'
        exp_opts['collections'] = ['test-collection-1', 'test-collection-2']
        assert search_query.params == exp_opts

        # client_context_id
        opts = SearchOptions(client_context_id='test-id')
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q, opts
        )
        exp_opts = base_opts.copy()
        exp_opts['client_context_id'] = 'test-id'
        assert search_query.params == exp_opts

        # timeout
        opts = SearchOptions(timeout=timedelta(seconds=20))
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q, opts
        )
        exp_opts = base_opts.copy()
        exp_opts['timeout'] = float(timedelta(seconds=20).total_seconds())
        assert search_query.params == exp_opts

        # facets
        opts = SearchOptions(facets={
            'term': search.TermFacet('somefield', limit=10),
            'dr': search.DateFacet('datefield').add_range('name', 'start', 'end'),
            'nr': search.NumericFacet('numfield').add_range('name2', 0.0, 99.99)
        })
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q, opts
        )
        exp_opts = base_opts.copy()
        exp_opts['facets'] = {
            'term': {
                'field': 'somefield',
                'size': 10
            },
            'dr': {
                'field': 'datefield',
                'date_ranges': [{
                    'name': 'name',
                    'start': 'start',
                    'end': 'end'
                }]
            },
            'nr': {
                'field': 'numfield',
                'numeric_ranges': [{
                    'name': 'name2',
                    'min': 0.0,
                    'max': 99.99
                }]
            },
        }

        params = search_query.params
        # handle encoded here
        encoded_facets = {}
        for name, facet in search_query.facets.items():
            encoded_facets[name] = facet.encodable
        params['facets'] = encoded_facets
        assert params == exp_opts

    def test_consistent_with(self):
        q = search.TermQuery('someterm')

        ms = MutationState()
        mt = MutationToken(token={
            'partition_id': 42,
            'partition_uuid': 3004,
            'sequence_number': 3,
            'bucket_name': 'default'
        })
        ms._add_scanvec(mt)
        opts = SearchOptions(consistent_with=ms)
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q, opts
        )

        # couchbase++ will set scan_consistency, so params should be
        # None, but the prop should return AT_PLUS
        assert search_query.params.get('scan_consistency', None) is None
        assert search_query.consistency == search.SearchScanConsistency.AT_PLUS

        q_mt = search_query.params.get('mutation_state', None)
        assert isinstance(q_mt, list)
        assert len(q_mt) == 1
        assert q_mt[0] == mt

    def test_facets(self):
        q = search.TermQuery('someterm')

        f = search.NumericFacet('numfield')
        with pytest.raises(InvalidArgumentException):
            f.add_range('range1')

        opts = SearchOptions()
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q, opts
        )
        with pytest.raises(InvalidArgumentException):
            search_query.facets['facetName'] = f

        search_query.facets['facetName'] = f.add_range('range1', min=123, max=321)
        assert 'facetName' in search_query.facets

        f = search.DateFacet('datefield')
        f.add_range('r1', start='2012', end='2013')
        f.add_range('r2', start='2014')
        f.add_range('r3', end='2015')
        opts = SearchOptions(facets={'facetName': f})
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q, opts
        )

        exp = {
            'field': 'datefield',
            'date_ranges': [
                {'name': 'r1', 'start': '2012', 'end': '2013'},
                {'name': 'r2', 'start': '2014'},
                {'name': 'r3', 'end': '2015'}
            ]
        }
        encoded_facets = {}
        for name, facet in search_query.facets.items():
            encoded_facets[name] = facet.encodable

        assert encoded_facets['facetName'] == exp
        # self.assertEqual(exp, f.encodable)

        f = search.TermFacet('termfield')
        f.limit = 10
        opts = SearchOptions(facets={'facetName': f})
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q, opts
        )
        encoded_facets = {}
        for name, facet in search_query.facets.items():
            encoded_facets[name] = facet.encodable

        assert encoded_facets['facetName'] == {'field': 'termfield', 'size': 10}

    def test_term_search(self):
        q = search.TermQuery('someterm', field='field', boost=1.5,
                             prefix_length=23, fuzziness=12)
        opts = search.SearchOptions(explain=True)

        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q, opts
        )

        encoded_q = self.get_encoded_query(search_query)

        exp_json = {
            'query': {
                'term': 'someterm',
                'boost': 1.5,
                'fuzziness': 12,
                'prefix_length': 23,
                'field': 'field'
            },
            'index_name': self.IDX_NAME,
            'explain': True
        }

        assert exp_json == encoded_q

    def test_match_phrase(self):
        exp_json = {
            'query': {
                'match_phrase': 'salty beers',
                'analyzer': 'analyzer',
                'boost': 1.5,
                'field': 'field'
            },
            'limit': 10,
            'index_name': self.IDX_NAME
        }

        q = search.MatchPhraseQuery('salty beers', boost=1.5, analyzer='analyzer',
                                    field='field')
        opts = search.SearchOptions(limit=10)

        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q, opts
        )

        encoded_q = self.get_encoded_query(search_query)

        assert exp_json == encoded_q

    def test_match_query(self):
        exp_json = {
            'query': {
                'match': 'salty beers',
                'analyzer': 'analyzer',
                'boost': 1.5,
                'field': 'field',
                'fuzziness': 1234,
                'prefix_length': 4,
                'operator': 'or'
            },
            'limit': 10,
            'index_name': self.IDX_NAME
        }

        q = search.MatchQuery('salty beers', boost=1.5, analyzer='analyzer',
                              field='field', fuzziness=1234, prefix_length=4, match_operator=MatchOperator.OR)
        opts = search.SearchOptions(limit=10)

        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q, opts
        )
        encoded_q = self.get_encoded_query(search_query)
        assert exp_json == encoded_q

        exp_json["query"]["operator"] = "and"

        q = search.MatchQuery('salty beers', boost=1.5, analyzer='analyzer',
                              field='field', fuzziness=1234, prefix_length=4, match_operator=MatchOperator.AND)
        opts = search.SearchOptions(limit=10)

        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q, opts
        )
        encoded_q = self.get_encoded_query(search_query)
        assert exp_json == encoded_q

    def test_string_query(self):
        exp_json = {
            'query': {
                'query': 'q*ry',
                'boost': 2.0,
            },
            'explain': True,
            'limit': 10,
            'index_name': self.IDX_NAME
        }
        q = search.QueryStringQuery('q*ry', boost=2.0)
        opts = search.SearchOptions(limit=10, explain=True)
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q, opts
        )
        encoded_q = self.get_encoded_query(search_query)
        assert exp_json == encoded_q

    def test_raw_query(self):
        exp_json = {
            'query': {
                'foo': 'bar'
            },
            'index_name': self.IDX_NAME
        }
        q = search.RawQuery({'foo': 'bar'})
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        encoded_q = self.get_encoded_query(search_query)
        assert exp_json == encoded_q

    def test_wildcard_query(self):
        exp_json = {
            'query': {
                'wildcard': 'f*o',
                'field': 'wc',
            },
            'index_name': self.IDX_NAME
        }
        q = search.WildcardQuery('f*o', field='wc')
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        encoded_q = self.get_encoded_query(search_query)
        assert exp_json == encoded_q

    def test_docid_query(self):
        q = search.DocIdQuery([])
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        with pytest.raises(search.NoChildrenException):
            _ = self.get_encoded_query(search_query)

        exp_json = {
            'query': {
                'ids': ['foo', 'bar', 'baz']
            },
            'index_name': self.IDX_NAME
        }

        q.ids = ['foo', 'bar', 'baz']
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        encoded_q = self.get_encoded_query(search_query)
        assert exp_json == encoded_q

    def test_match_all_query(self):
        exp_json = {
            'query': {
                'match_all': None
            },
            'index_name': self.IDX_NAME
        }
        q = search.MatchAllQuery()
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        encoded_q = self.get_encoded_query(search_query)
        assert exp_json == encoded_q

    def test_match_none_query(self):
        exp_json = {
            'query': {
                'match_none': None
            },
            'index_name': self.IDX_NAME
        }
        q = search.MatchNoneQuery()
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        encoded_q = self.get_encoded_query(search_query)
        assert exp_json == encoded_q

    def test_phrase_query(self):
        exp_json = {
            'query': {
                'terms': ['salty', 'beers']
            },
            'index_name': self.IDX_NAME
        }
        q = search.PhraseQuery('salty', 'beers')
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        encoded_q = self.get_encoded_query(search_query)
        assert exp_json == encoded_q

        q = search.PhraseQuery()
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        with pytest.raises(search.NoChildrenException):
            _ = self.get_encoded_query(search_query)

        q.terms.append('salty')
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        encoded_q = self.get_encoded_query(search_query)
        exp_json['query']['terms'] = ['salty']
        assert exp_json == encoded_q

    def test_prefix_query(self):
        exp_json = {
            'query': {
                'prefix': 'someterm',
                'boost': 1.5
            },
            'index_name': self.IDX_NAME
        }
        q = search.PrefixQuery('someterm', boost=1.5)
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        encoded_q = self.get_encoded_query(search_query)
        assert exp_json == encoded_q

    def test_regexp_query(self):
        exp_json = {
            'query': {
                'regex': 'some?regex'
            },
            'index_name': self.IDX_NAME
        }
        q = search.RegexQuery('some?regex')
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        encoded_q = self.get_encoded_query(search_query)
        assert exp_json == encoded_q

    def test_booleanfield_query(self):
        exp_json = {
            'query': {
                'bool': True
            },
            'index_name': self.IDX_NAME
        }
        q = search.BooleanFieldQuery(True)
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        encoded_q = self.get_encoded_query(search_query)
        assert exp_json == encoded_q

    def test_daterange_query(self):
        with pytest.raises(TypeError):
            q = search.DateRangeQuery()

        q = search.DateRangeQuery(end='theEnd')
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        encoded_q = self.get_encoded_query(search_query)
        assert encoded_q['query'] == {'end': 'theEnd'}

        q = search.DateRangeQuery(start='theStart')
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        encoded_q = self.get_encoded_query(search_query)
        assert encoded_q['query'] == {'start': 'theStart'}

        q = search.DateRangeQuery(start='theStart', end='theEnd')
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        encoded_q = self.get_encoded_query(search_query)
        assert encoded_q['query'] == {'start': 'theStart', 'end': 'theEnd'}

        q = search.DateRangeQuery('', '')  # Empty strings should be ok
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        encoded_q = self.get_encoded_query(search_query)
        assert encoded_q['query'] == {'start': '', 'end': ''}

    def test_numrange_query(self):
        with pytest.raises(TypeError):
            q = search.NumericRangeQuery()

        q = search.NumericRangeQuery(0, 0)  # Should be OK
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        encoded_q = self.get_encoded_query(search_query)
        assert encoded_q['query'] == {'min': 0, 'max': 0}

        q = search.NumericRangeQuery(0.1, 0.9)
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        encoded_q = self.get_encoded_query(search_query)
        assert encoded_q['query'] == {'min': 0.1, 'max': 0.9}

        q = search.NumericRangeQuery(max=0.9)
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        encoded_q = self.get_encoded_query(search_query)
        assert encoded_q['query'] == {'max': 0.9}

        q = search.NumericRangeQuery(min=0.1)
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        encoded_q = self.get_encoded_query(search_query)
        assert encoded_q['query'] == {'min': 0.1}

    def test_termrange_query(self):
        with pytest.raises(TypeError):
            q = search.TermRangeQuery()

        q = search.TermRangeQuery('', '')  # Should be OK
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        encoded_q = self.get_encoded_query(search_query)
        assert encoded_q['query'] == {'start': '', 'end': ''}

        q = search.TermRangeQuery('startTerm', 'endTerm')
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        encoded_q = self.get_encoded_query(search_query)
        assert encoded_q['query'] == {'start': 'startTerm', 'end': 'endTerm'}

        q = search.TermRangeQuery(end='endTerm')
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        encoded_q = self.get_encoded_query(search_query)
        assert encoded_q['query'] == {'end': 'endTerm'}

        q = search.TermRangeQuery(start='startTerm')
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        encoded_q = self.get_encoded_query(search_query)
        assert encoded_q['query'] == {'start': 'startTerm'}

    def test_boolean_query(self):
        prefix_q = search.PrefixQuery('someterm', boost=2)
        bool_q = search.BooleanQuery(
            must=prefix_q, must_not=prefix_q, should=prefix_q)
        exp = {'prefix': 'someterm', 'boost': 2.0}
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, bool_q
        )
        encoded_q = self.get_encoded_query(search_query)

        conjuncts = {
            'conjuncts': [exp]
        }
        disjuncts = {
            'disjuncts': [exp],
            'min': 1
        }
        assert encoded_q['query']['must'] == conjuncts
        assert encoded_q['query']['must_not'] == disjuncts
        assert encoded_q['query']['should'] == disjuncts

        # Test multiple criteria in must and must_not
        pq_1 = search.PrefixQuery('someterm', boost=2)
        pq_2 = search.PrefixQuery('otherterm')
        bool_q = search.BooleanQuery(must=[pq_1, pq_2])
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, bool_q
        )
        encoded_q = self.get_encoded_query(search_query)
        conjuncts = {
            'conjuncts': [
                {'prefix': 'someterm', 'boost': 2.0},
                {'prefix': 'otherterm'}
            ]
        }
        assert encoded_q['query']['must'] == conjuncts

    def test_disjunction_query(self):
        q = search.DisjunctionQuery()
        assert q.min == 1
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        with pytest.raises(search.NoChildrenException):
            _ = self.get_encoded_query(search_query)

        disjuncts = {
            'disjuncts': [{'prefix': 'somePrefix'}],
            'min': 1
        }
        q.disjuncts.append(search.PrefixQuery('somePrefix'))
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        encoded_q = self.get_encoded_query(search_query)
        assert encoded_q['query'] == disjuncts

        with pytest.raises(InvalidArgumentException):
            q.min = 0

        q.min = 2
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        with pytest.raises(InvalidArgumentException):
            _ = self.get_encoded_query(search_query)

    def test_conjunction_query(self):
        q = search.ConjunctionQuery()
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        with pytest.raises(search.NoChildrenException):
            _ = self.get_encoded_query(search_query)

        conjuncts = {
            'conjuncts': [{'prefix': 'somePrefix'}],
        }
        q.conjuncts.append(search.PrefixQuery('somePrefix'))
        search_query = search.SearchQueryBuilder.create_search_query_object(
            self.IDX_NAME, q
        )
        encoded_q = self.get_encoded_query(search_query)
        assert encoded_q['query'] == conjuncts
