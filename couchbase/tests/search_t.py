import json
import pathlib
from os import path
from typing import (List,
                    Optional,
                    Union)

import pytest

import couchbase.search as search
from couchbase.auth import PasswordAuthenticator
from couchbase.cluster import Cluster
from couchbase.exceptions import InvalidArgumentException, SearchIndexNotFoundException
from couchbase.management.search import SearchIndex
from couchbase.options import ClusterOptions
from couchbase.result import SearchResult
from couchbase.search import (HighlightStyle,
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

    @pytest.fixture(scope="class", name="cb_env")
    def couchbase_test_environment(self, couchbase_config):
        conn_string = couchbase_config.get_connection_string()
        username, pw = couchbase_config.get_username_and_pw()
        opts = ClusterOptions(PasswordAuthenticator(username, pw))
        cluster = Cluster(
            conn_string, opts)
        cluster.cluster_info()
        bucket = cluster.bucket(f"{couchbase_config.bucket_name}")

        coll = bucket.default_collection()
        cb_env = TestEnvironment(cluster,
                                 bucket,
                                 coll,
                                 couchbase_config,
                                 manage_buckets=True,
                                 manage_search_indexes=True)

        cb_env.load_data()
        self._load_search_index(cb_env)
        yield cb_env
        cb_env.purge_data()
        self._drop_search_index(cb_env)
        cluster.close()

    def _load_search_index(self, cb_env):
        with open(self.TEST_INDEX_PATH) as params_file:
            input = params_file.read()
            params_json = json.loads(input)
            try:
                cb_env.sixm.get_index(self.TEST_INDEX_NAME)
                # wait at least 5 minutes
                self._check_indexed_docs(cb_env, retries=30, delay=10)
            except Exception:
                cb_env.sixm.upsert_index(
                    SearchIndex(name=self.TEST_INDEX_NAME,
                                idx_type='fulltext-index',
                                source_name='default',
                                source_type='couchbase',
                                params=params_json)
                )
                # make sure the index loads...
                self._check_indexed_docs(cb_env, retries=30, delay=10)

    def _check_indexed_docs(self, cb_env, retries=20, delay=30, num_docs=20, idx='test-search-index'):
        indexed_docs = 0
        no_docs_cutoff = 300
        for i in range(retries):
            # if no docs after waiting for a period of time, exit
            if indexed_docs == 0 and i * delay >= no_docs_cutoff:
                return 0
            indexed_docs = cb_env.try_n_times(
                10, 10, cb_env.sixm.get_indexed_documents_count, idx)
            if indexed_docs >= num_docs:
                break
            print(f'Found {indexed_docs} indexed docs, waiting a bit...')
            cb_env.sleep(delay)

        return indexed_docs

    @pytest.fixture(scope="class")
    def check_disable_scoring_supported(self, cb_env):
        cb_env.check_if_feature_supported('search_disable_scoring')

    def _drop_search_index(self, cb_env):
        try:
            cb_env.sixm.drop_index(self.TEST_INDEX_NAME)
        except SearchIndexNotFoundException:
            pass
        except Exception as ex:
            raise ex

    def assert_rows(self,
                    result,  # type: SearchResult
                    expected_count,  # type: int
                    return_rows=False  # type: bool
                    ) -> Optional[List[Union[SearchRow, dict]]]:
        rows = []
        assert isinstance(result, SearchResult)
        for row in result.rows():
            assert row is not None
            rows.append(row)
        assert len(rows) >= expected_count

        if return_rows is True:
            return rows

    def test_cluster_search(self, cb_env):
        q = search.TermQuery('home')
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10))
        self.assert_rows(res, 2)

    def test_cluster_search_fields(self, cb_env):
        test_fields = ['name', 'activity']
        q = search.TermQuery('home')
        # verify fields works w/in kwargs
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10), fields=test_fields)

        rows = self.assert_rows(res, 1, return_rows=True)
        first_entry = rows[0]
        assert isinstance(first_entry, SearchRow)
        assert isinstance(first_entry.fields, dict)
        assert first_entry.fields != {}
        res = list(map(lambda f: f in test_fields, first_entry.fields.keys()))
        assert all(map(lambda f: f in test_fields, first_entry.fields.keys())) is True

        # verify fields works w/in options
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10, fields=test_fields))

        rows = self.assert_rows(res, 1, return_rows=True)
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

    def test_cluster_search_top_level_facets(self, cb_env):
        # if the facet limit is omitted, the details of the facets will not be provided
        # (i.e. SearchFacetResult.terms is None,
        #       SearchFacetResult.numeric_ranges is None and SearchFacetResult.date_ranges is None)
        facet_name = 'activity'
        facet = search.TermFacet('activity')
        q = search.TermQuery('home')
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10, facets={facet_name: facet}))

        self.assert_rows(res, 1)
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

        self.assert_rows(res, 1)
        facets = res.facets()
        assert isinstance(facets, dict)
        result_facet = facets[facet_name]
        assert isinstance(result_facet, SearchFacetResult)
        assert result_facet.name == facet_name
        assert result_facet.field == facet_name
        assert result_facet.terms is None
        assert result_facet.numeric_ranges is None
        assert result_facet.date_ranges is None

    def test_cluster_search_top_level_facets_kwargs(self, cb_env):
        # if the facet limit is omitted, the details of the facets will not be provided
        # (i.e. SearchFacetResult.terms is None,
        #       SearchFacetResult.numeric_ranges is None and SearchFacetResult.date_ranges is None)
        facet_name = 'activity'
        facet = search.TermFacet('activity')
        q = search.TermQuery('home')
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10), facets={facet_name: facet})

        self.assert_rows(res, 1)
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

        self.assert_rows(res, 1)
        facets = res.facets()
        assert isinstance(facets, dict)
        result_facet = facets[facet_name]
        assert isinstance(result_facet, SearchFacetResult)
        assert result_facet.name == facet_name
        assert result_facet.field == facet_name
        assert result_facet.terms is None
        assert result_facet.numeric_ranges is None
        assert result_facet.date_ranges is None

    def test_cluster_search_term_facets(self, cb_env):

        facet_name = 'activity'
        facet = search.TermFacet('activity', 5)
        q = search.TermQuery('home')
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10, facets={facet_name: facet}))

        self.assert_rows(res, 1)
        facets = res.facets()
        assert isinstance(facets, dict)
        result_facet = facets[facet_name]
        assert isinstance(result_facet, SearchFacetResult)
        assert result_facet.name == facet_name
        assert result_facet.field == facet_name
        assert all(map(lambda ft: isinstance(ft, SearchTermFacet), result_facet.terms)) is True
        assert len(result_facet.terms) <= facet.limit

    def test_cluster_search_numeric_facets(self, cb_env):

        facet_name = 'rating'
        facet = search.NumericFacet('rating', limit=3)
        facet.add_range('low', max=2)
        facet.add_range('med', min=2, max=4)
        facet.add_range('high', min=4)
        q = search.TermQuery('home')
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10, facets={facet_name: facet}))

        self.assert_rows(res, 1)
        facets = res.facets()
        assert isinstance(facets, dict)
        result_facet = facets[facet_name]
        assert isinstance(result_facet, SearchFacetResult)
        assert result_facet.name == facet_name
        assert result_facet.field == facet_name
        assert all(map(lambda ft: isinstance(ft, SearchNumericRangeFacet), result_facet.numeric_ranges)) is True
        assert len(result_facet.numeric_ranges) <= facet.limit

    def test_cluster_search_date_facets(self, cb_env):
        facet_name = 'updated'
        facet = search.DateFacet('updated', limit=3)
        facet.add_range('early', end='2022-02-02T00:00:00Z')
        facet.add_range('mid', start='2022-02-03T00:00:00Z',
                        end='2022-03-03T00:00:00Z')
        facet.add_range('late', start='2022-03-04T00:00:00Z')
        q = search.TermQuery('home')
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10, facets={facet_name: facet}))

        self.assert_rows(res, 1)
        facets = res.facets()
        assert isinstance(facets, dict)
        result_facet = facets[facet_name]
        assert isinstance(result_facet, SearchFacetResult)
        assert result_facet.name == facet_name
        assert result_facet.field == facet_name
        assert all(map(lambda ft: isinstance(ft, SearchDateRangeFacet), result_facet.date_ranges)) is True
        assert len(result_facet.date_ranges) <= facet.limit

    @pytest.mark.usefixtures('check_disable_scoring_supported')
    def test_cluster_search_disable_scoring(self, cb_env):

        # verify disable scoring works w/in SearchOptions
        q = search.TermQuery('home')
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10, disable_scoring=True))
        rows = self.assert_rows(res, 1, return_rows=True)
        assert all(map(lambda r: r.score == 0, rows)) is True

        # verify disable scoring works w/in kwargs
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10), disable_scoring=True)
        rows = self.assert_rows(res, 1, return_rows=True)
        assert all(map(lambda r: r.score == 0, rows)) is True

        # verify setting disable_scoring to False works
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10, disable_scoring=False))
        rows = self.assert_rows(res, 1, return_rows=True)
        assert all(map(lambda r: r.score != 0, rows)) is True

        # verify default disable_scoring is False
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10))
        rows = self.assert_rows(res, 1, return_rows=True)
        assert all(map(lambda r: r.score != 0, rows)) is True

    def test_cluster_search_highlight(self, cb_env):

        q = search.TermQuery('home')
        # check w/in options
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10, highlight_style=HighlightStyle.Html))
        rows = self.assert_rows(res, 1, return_rows=True)
        locations = rows[0].locations
        fragments = rows[0].fragments
        assert isinstance(locations, search.SearchRowLocations)
        assert isinstance(fragments, dict)
        assert all(map(lambda l: isinstance(l, search.SearchRowLocation), locations.get_all())) is True

        # check w/in options
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10), highlight_style=HighlightStyle.Html)
        rows = self.assert_rows(res, 1, return_rows=True)
        locations = rows[0].locations
        fragments = rows[0].fragments
        assert isinstance(locations, search.SearchRowLocations)
        assert isinstance(fragments, dict)
        assert all(map(lambda l: isinstance(l, search.SearchRowLocation), locations.get_all())) is True

    # @TODO(PYCBC-1296):  DIFF between 3.x and 4.x, locations returns None
    def test_search_no_include_locations(self, cb_env):
        q = search.TermQuery('home')
        # check w/in options
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10, include_locations=False))
        rows = self.assert_rows(res, 1, return_rows=True)
        locations = rows[0].locations
        assert locations is None

        # check w/in kwargs
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10), include_locations=False)
        rows = self.assert_rows(res, 1, return_rows=True)
        locations = rows[0].locations
        assert locations is None

    def test_search_include_locations(self, cb_env):
        q = search.TermQuery('home')
        # check w/in options
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10, include_locations=True))
        rows = self.assert_rows(res, 1, return_rows=True)
        locations = rows[0].locations
        assert isinstance(locations, search.SearchRowLocations)
        assert all(map(lambda l: isinstance(l, search.SearchRowLocation), locations.get_all())) is True

        # check w/in kwargs
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10), include_locations=True)
        rows = self.assert_rows(res, 1, return_rows=True)
        locations = rows[0].locations
        assert isinstance(locations, search.SearchRowLocations)
        assert all(map(lambda l: isinstance(l, search.SearchRowLocation), locations.get_all())) is True

    def test_cluster_search_scan_consistency(self, cb_env):
        q = search.TermQuery('home')
        # check w/in options
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10, scan_consistency=search.SearchScanConsistency.NOT_BOUNDED))
        self.assert_rows(res, 1)

        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10, scan_consistency=search.SearchScanConsistency.REQUEST_PLUS))
        self.assert_rows(res, 1)

        with pytest.raises(InvalidArgumentException):
            cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
                limit=10, scan_consistency=search.SearchScanConsistency.AT_PLUS))

    @pytest.mark.parametrize('operator, query_terms, expect_rows',
                             [(search.MatchOperator.AND, "home hollywood", True),
                              (search.MatchOperator.AND, "home :random:", False),
                              (search.MatchOperator.OR, "home hollywood", True),
                              (search.MatchOperator.OR, "home :random:", True)])
    def test_search_match_operator(self, cb_env, operator, query_terms, expect_rows):
        import random
        import string

        random_query_term = "".join(random.choice(string.ascii_letters)
                                    for _ in range(10))

        if ':random:' in query_terms:
            query_terms.replace(':random:', random_query_term)

        q = search.MatchQuery(query_terms, match_operator=operator)

        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, limit=10)
        rows = self.assert_rows(res, 0, return_rows=True)

        if expect_rows:
            assert len(rows) > 0
        else:
            assert len(rows) == 0

    def test_search_match_operator_fail(self, cb_env):
        with pytest.raises(ValueError):
            q = search.MatchQuery('home hollywood', match_operator='NOT')
            cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, limit=10)

    def test_search_raw_query(self, cb_env):
        query_args = {"match": "home hollywood",
                      "fuzziness": 2, "operator": "and"}
        q = search.RawQuery(query_args)
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, limit=10)
        self.assert_rows(res, 1)

    # @TODO:  couchbase++ doesn't seem to do the raw sort correctly
    def test_cluster_sort_str(self, cb_env):
        q = search.TermQuery('home')
        # score - ascending
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10, sort=['_score']))
        _ = self.assert_rows(res, 1, return_rows=True)
        # print(rows)
        # score = rows[0].score
        # for row in rows[1:]:
        #     assert row.score >= score
        #     score = row.score

        # score - descending
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10, sort=['-_score']))
        _ = self.assert_rows(res, 1, return_rows=True)
        # print(rows)
        # score = rows[0].score
        # for row in rows[1:]:
        #     assert score >= row.score
        #     score = row.score

    def test_cluster_sort_score(self, cb_env):
        q = search.TermQuery('home')
        # score - ascending
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10, sort=[search.SortScore()]))
        rows = self.assert_rows(res, 1, return_rows=True)

        score = rows[0].score
        for row in rows[1:]:
            assert row.score >= score
            score = row.score

        # score - descending
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10, sort=[search.SortScore(desc=True)]))
        rows = self.assert_rows(res, 1, return_rows=True)

        score = rows[0].score
        for row in rows[1:]:
            assert score >= row.score
            score = row.score

    def test_cluster_sort_id(self, cb_env):
        q = search.TermQuery('home')
        # score - ascending
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(limit=10, sort=[search.SortID()]))
        rows = self.assert_rows(res, 1, return_rows=True)

        id = rows[0].id
        for row in rows[1:]:
            assert row.id >= id
            id = row.id

        # score - descending
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10, sort=[search.SortID(desc=True)]))
        rows = self.assert_rows(res, 1, return_rows=True)

        id = rows[0].id
        for row in rows[1:]:
            assert id >= row.id
            id = row.id

    def test_cluster_sort_field(self, cb_env):
        sort_field = "rating"
        q = search.TermQuery('home')
        # field - ascending
        sort = search.SortField(field=sort_field, type="number", mode="min", missing="last")
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10, sort=[sort], fields=[sort_field]))

        rows = self.assert_rows(res, 1, return_rows=True)
        rating = rows[0].fields[sort_field]
        for row in rows[1:]:
            assert row.fields[sort_field] >= rating
            rating = row.fields[sort_field]

        # field - descending
        sort.desc = True
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10, sort=[sort], fields=[sort_field]))

        rows = self.assert_rows(res, 1, return_rows=True)
        rating = rows[0].fields[sort_field]
        for row in rows[1:]:
            assert rating >= row.fields[sort_field]
            rating = row.fields[sort_field]

    def test_cluster_sort_geo(self, cb_env):
        # @TODO:  better confirmation on results?
        sort_field = "geo"
        q = search.TermQuery('home')
        # geo - ascending
        sort = search.SortGeoDistance(field=sort_field, location=(37.7749, 122.4194), unit="meters")
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10, sort=[sort], fields=[sort_field]))
        self.assert_rows(res, 1)

        # geo - descending
        sort.desc = True
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10, sort=[sort], fields=[sort_field]))
        self.assert_rows(res, 1)

    def test_cluster_sort_field_multi(self, cb_env):
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
        self.assert_rows(res, 1)

        sort_fields = [
            search.SortField(field="rating", type="number",
                             mode="min", missing="last", desc=True),
            search.SortField(field="updated", type="number",
                             mode="min", missing="last"),
            search.SortScore(desc=True),
        ]
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10, sort=sort_fields, fields=sort_field_names))
        self.assert_rows(res, 1)

        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10, sort=["abv", "udpated", "-_score"]))
        self.assert_rows(res, 1)


class SearchCollectionTests:
    TEST_INDEX_NAME = 'test-search-coll-index'
    TEST_INDEX_PATH = path.join(pathlib.Path(__file__).parent.parent.parent,
                                'tests',
                                'test_cases',
                                f'{TEST_INDEX_NAME}-params.json')

    @pytest.fixture(scope="class", name="cb_env")
    def couchbase_test_environment(self, couchbase_config):
        conn_string = couchbase_config.get_connection_string()
        username, pw = couchbase_config.get_username_and_pw()
        opts = ClusterOptions(PasswordAuthenticator(username, pw))
        cluster = Cluster(
            conn_string, opts)
        cluster.on_connect()
        cluster.cluster_info()
        bucket = cluster.bucket(f"{couchbase_config.bucket_name}")
        cluster.on_connect()

        coll = bucket.default_collection()
        cb_env = TestEnvironment(cluster,
                                 bucket,
                                 coll,
                                 couchbase_config,
                                 manage_buckets=True,
                                 manage_collections=True,
                                 manage_search_indexes=True)
        cb_env.setup_named_collections()

        cb_env.load_data()
        self._load_search_index(cb_env)
        yield cb_env
        cb_env.purge_data()
        cb_env.teardown_named_collections()
        self._drop_search_index(cb_env)
        cluster.close()

    def _load_search_index(self, cb_env):
        with open(self.TEST_INDEX_PATH) as params_file:
            input = params_file.read()
            params_json = json.loads(input)
            try:
                cb_env.sixm.get_index(self.TEST_INDEX_NAME)
                # wait at least 5 minutes
                self._check_indexed_docs(cb_env, retries=30, delay=10)
            except Exception:
                cb_env.sixm.upsert_index(
                    SearchIndex(name=self.TEST_INDEX_NAME,
                                idx_type='fulltext-index',
                                source_name='default',
                                source_type='couchbase',
                                params=params_json)
                )
                # make sure the index loads...
                self._check_indexed_docs(cb_env, retries=30, delay=10)

    def _check_indexed_docs(self, cb_env, retries=20, delay=30, num_docs=20, idx='test-search-coll-index'):
        indexed_docs = 0
        no_docs_cutoff = 300
        for i in range(retries):
            # if no docs after waiting for a period of time, exit
            if indexed_docs == 0 and i * delay >= no_docs_cutoff:
                return 0
            indexed_docs = cb_env.try_n_times(
                10, 10, cb_env.sixm.get_indexed_documents_count, idx)
            if indexed_docs >= num_docs:
                break
            print(f'Found {indexed_docs} indexed docs, waiting a bit...')
            cb_env.sleep(delay)

        return indexed_docs

    def _drop_search_index(self, cb_env):
        try:
            cb_env.sixm.drop_index(self.TEST_INDEX_NAME)
        except SearchIndexNotFoundException:
            pass
        except Exception as ex:
            raise ex

    def assert_rows(self,
                    result,  # type: SearchResult
                    expected_count,  # type: int
                    return_rows=False  # type: bool
                    ) -> Optional[List[Union[SearchRow, dict]]]:
        rows = []
        assert isinstance(result, SearchResult)
        for row in result.rows():
            assert row is not None
            rows.append(row)
        assert len(rows) >= expected_count

        if return_rows is True:
            return rows

    # @TODO:  maybe need multiple collections...
    def test_cluster_query_collections(self, cb_env):
        q = search.TermQuery('home')
        res = cb_env.cluster.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10, scope_name=cb_env.scope.name, collections=[cb_env.collection.name]))
        _ = self.assert_rows(res, 2, return_rows=True)

        # rows = x.rows()
        # collections = list(map(lambda r: r.fields['_$c'], rows))
        # self.assertTrue(all([c for c in collections if c == 'breweries']))
        # SearchResultTest._check_search_result(self, initial, 1, x)

    def test_scope_query_collections(self, cb_env):
        q = search.TermQuery('home')
        res = cb_env.scope.search_query(self.TEST_INDEX_NAME, q, SearchOptions(
            limit=10, collections=[cb_env.collection.name]))
        self.assert_rows(res, 2)
