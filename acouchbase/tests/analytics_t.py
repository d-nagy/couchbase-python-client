import asyncio
from datetime import datetime, timedelta

import pytest
import pytest_asyncio

from acouchbase.cluster import Cluster, get_event_loop
from couchbase.analytics import (AnalyticsMetaData,
                                 AnalyticsMetrics,
                                 AnalyticsStatus,
                                 AnalyticsWarning)
from couchbase.auth import PasswordAuthenticator
from couchbase.exceptions import ParsingFailedException
from couchbase.management.options import ConnectLinkOptions, DisconnectLinkOptions
from couchbase.options import (AnalyticsOptions,
                               ClusterOptions,
                               UnsignedInt64)
from couchbase.result import AnalyticsResult

from ._test_utils import TestEnvironment


class AnalyticsTests:

    DATASET_NAME = 'test-dataset'

    @pytest_asyncio.fixture(scope="class")
    def event_loop(self):
        loop = get_event_loop()
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
        cb_env = TestEnvironment(cluster, bucket, coll, couchbase_config, manage_analytics=True)

        # setup
        await cb_env.load_data()
        dv_name = 'test/dataverse' if cb_env.server_version_short >= 7.0 else 'test_dataverse'
        await cb_env.am.create_dataverse(dv_name, ignore_if_exists=True)
        await cb_env.am.create_dataset(self.DATASET_NAME, cb_env.bucket.name, ignore_if_exists=True)
        await cb_env.am.connect_link(ConnectLinkOptions(dataverse_name=dv_name))

        q_str = f'SELECT COUNT(1) AS doc_count FROM `{self.DATASET_NAME}`;'

        for _ in range(10):
            res = cluster.analytics_query(q_str)
            rows = [r async for r in res.rows()]
            print(rows)
            if len(rows) > 0 and rows[0].get('doc_count', 0) > 10:
                break
            print(f'Found {len(rows)} records, waiting a bit...')
            await asyncio.sleep(5)

        yield cb_env

        # teardown
        await cb_env.purge_data()
        await cb_env.am.disconnect_link(DisconnectLinkOptions(dataverse_name=dv_name))
        await cb_env.am.drop_dataset(self.DATASET_NAME, ignore_if_not_exists=True)
        await cb_env.am.drop_dataverse(dv_name, ignore_if_not_exists=True)
        await cluster.close()

    async def assert_rows(self,
                          result,  # type: AnalyticsResult
                          expected_count):
        count = 0
        assert isinstance(result, AnalyticsResult)
        async for row in result.rows():
            assert row is not None
            count += 1
        assert count >= expected_count

    @pytest.mark.asyncio
    async def test_simple_query(self, cb_env):
        result = cb_env.cluster.analytics_query(f"SELECT * FROM `{self.DATASET_NAME}` LIMIT 1")
        await self.assert_rows(result, 1)

    @pytest.mark.asyncio
    async def test_query_positional_params(self, cb_env):
        result = cb_env.cluster.analytics_query(f'SELECT * FROM `{self.DATASET_NAME}` WHERE `type` = $1 LIMIT 1',
                                                AnalyticsOptions(positional_parameters=["airline"]))
        await self.assert_rows(result, 1)

    @pytest.mark.asyncio
    async def test_query_positional_params_no_option(self, cb_env):
        result = cb_env.cluster.analytics_query(
            f'SELECT * FROM `{self.DATASET_NAME}` WHERE `type` = $1 LIMIT 1', 'airline')
        await self.assert_rows(result, 1)

    @pytest.mark.asyncio
    async def test_query_positional_params_override(self, cb_env):
        result = cb_env.cluster.analytics_query(f'SELECT * FROM `{self.DATASET_NAME}` WHERE `type` = $1 LIMIT 1',
                                                AnalyticsOptions(positional_parameters=['abcdefg']), 'airline')
        await self.assert_rows(result, 1)

    @pytest.mark.asyncio
    async def test_query_named_parameters(self, cb_env):
        result = cb_env.cluster.analytics_query(f'SELECT * FROM `{self.DATASET_NAME}` WHERE `type` = $type LIMIT 1',
                                                AnalyticsOptions(named_parameters={'type': 'airline'}))
        await self.assert_rows(result, 1)

    @pytest.mark.asyncio
    async def test_query_named_parameters_no_options(self, cb_env):
        result = cb_env.cluster.analytics_query(f'SELECT * FROM `{self.DATASET_NAME}` WHERE `type` = $atype LIMIT 1',
                                                atype='airline')
        await self.assert_rows(result, 1)

    @pytest.mark.asyncio
    async def test_query_named_parameters_override(self, cb_env):
        result = cb_env.cluster.analytics_query(f'SELECT * FROM `{self.DATASET_NAME}` WHERE `type` = $atype LIMIT 1',
                                                AnalyticsOptions(named_parameters={'atype': 'abcdefg'}),
                                                atype='airline')
        await self.assert_rows(result, 1)

    @pytest.mark.asyncio
    async def test_analytics_with_metrics(self, cb_env):
        initial = datetime.now()
        result = cb_env.cluster.analytics_query(f'SELECT * FROM `{self.DATASET_NAME}` LIMIT 1')
        await self.assert_rows(result, 1)
        taken = datetime.now() - initial
        metadata = result.metadata()  # type: AnalyticsMetaData
        metrics = metadata.metrics()
        assert isinstance(metrics, AnalyticsMetrics)
        assert isinstance(metrics.elapsed_time(), timedelta)
        assert metrics.elapsed_time() < taken
        assert metrics.elapsed_time() > timedelta(milliseconds=0)
        assert isinstance(metrics.execution_time(), timedelta)
        assert metrics.execution_time() < taken
        assert metrics.execution_time() > timedelta(milliseconds=0)

        expected_counts = {metrics.error_count: 0,
                           metrics.result_count: 1,
                           metrics.warning_count: 0}
        for method, expected in expected_counts.items():
            count_result = method()
            fail_msg = "{} failed".format(method)
            assert isinstance(count_result, UnsignedInt64), fail_msg
            assert count_result == UnsignedInt64(expected), fail_msg
        assert metrics.result_size() > UnsignedInt64(0)
        assert isinstance(metrics.processed_objects(), UnsignedInt64)
        assert metrics.error_count() == UnsignedInt64(0)

    @pytest.mark.asyncio
    async def test_analytics_metadata(self, cb_env):
        result = cb_env.cluster.analytics_query(f'SELECT * FROM `{self.DATASET_NAME}` LIMIT 2')
        await self.assert_rows(result, 2)
        metadata = result.metadata()  # type: AnalyticsMetaData
        assert isinstance(metadata, AnalyticsMetaData)
        for id_meth in (metadata.client_context_id, metadata.request_id):
            id_res = id_meth()
            fail_msg = "{} failed".format(id_meth)
            assert isinstance(id_res, str), fail_msg
        assert metadata.status() == AnalyticsStatus.SUCCESS
        assert isinstance(metadata.signature(), (str, dict))
        assert isinstance(metadata.warnings(), (list))
        for warning in metadata.warnings():
            assert isinstance(warning, AnalyticsWarning)
            assert isinstance(warning.message(), str)
            assert isinstance(warning.code(), int)


class AnalyticsCollectionTests:

    DATASET_NAME = 'test-dataset'

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
                                 manage_analytics=True,
                                 manage_collections=True)

        await cb_env.setup_named_collections()

        # setup
        await cb_env.load_data()
        await self.create_analytics_collections(cb_env)

        yield cb_env

        # teardown
        await cb_env.purge_data()
        await self.tear_down_analytics_collections(cb_env)
        await cb_env.teardown_named_collections()
        await cluster.close()

    async def create_analytics_collections(self, cb_env):

        dv_fqdn = f'`{cb_env.bucket.name}`.`{cb_env.scope.name}`'
        q_str = f'CREATE DATAVERSE {dv_fqdn} IF NOT EXISTS;'
        res = cb_env.cluster.analytics_query(q_str)
        [_ async for _ in res.rows()]
        # await cb_env.am.create_dataverse(dv_fqdn, ignore_if_exists=True)

        q_str = f'USE {dv_fqdn}; CREATE DATASET `{cb_env.collection.name}` IF NOT EXISTS ON {cb_env.fqdn}'
        res = cb_env.cluster.analytics_query(q_str)
        [_ async for _ in res.rows()]

        q_str = f'USE {dv_fqdn}; CONNECT LINK Local;'
        res = cb_env.cluster.analytics_query(q_str)
        [_ async for _ in res.rows()]

        q_str = f'SELECT COUNT(1) AS doc_count FROM `{self.DATASET_NAME}`;'

        for _ in range(10):
            res = cb_env.cluster.analytics_query(q_str)
            rows = [r async for r in res.rows()]
            print(rows)
            if len(rows) > 0 and rows[0].get('doc_count', 0) > 10:
                break
            print(f'Found {len(res)} records, waiting a bit...')
            await asyncio.sleep(5)

    async def tear_down_analytics_collections(self, cb_env):
        dv_fqdn = f'`{cb_env.bucket.name}`.`{cb_env.scope.name}`'
        q_str = f'USE {dv_fqdn}; DISCONNECT LINK Local;'
        res = cb_env.cluster.analytics_query(q_str)
        [_ async for _ in res.rows()]

        q_str = f'USE {dv_fqdn}; DROP DATASET `{cb_env.collection.name}` IF EXISTS; ON {cb_env.fqdn}'
        res = cb_env.cluster.analytics_query(q_str)
        [_ async for _ in res.rows()]

        q_str = f'DROP DATAVERSE {dv_fqdn} IF EXISTS;'
        res = cb_env.cluster.analytics_query(q_str)
        [_ async for _ in res.rows()]

    async def assert_rows(self,
                          result,  # type: AnalyticsResult
                          expected_count):
        count = 0
        assert isinstance(result, AnalyticsResult)
        async for row in result.rows():
            assert row is not None
            count += 1
        assert count >= expected_count

    @pytest.mark.asyncio
    async def test_query_fully_qualified(self, cb_env):
        result = cb_env.cluster.analytics_query(f'SELECT * FROM {cb_env.fqdn} LIMIT 2')
        await self.assert_rows(result, 2)

    @pytest.mark.asyncio
    async def test_cluster_query_context(self, cb_env):
        q_context = f'default:`{cb_env.bucket.name}`.`{cb_env.scope.name}`'
        # test with QueryOptions
        a_opts = AnalyticsOptions(query_context=q_context)
        result = cb_env.cluster.analytics_query(
            f'SELECT * FROM `{cb_env.collection.name}` LIMIT 2', a_opts)
        await self.assert_rows(result, 2)

        # test with kwargs
        result = cb_env.cluster.analytics_query(
            f'SELECT * FROM `{cb_env.collection.name}` LIMIT 2', query_context=q_context)
        await self.assert_rows(result, 2)

    @pytest.mark.asyncio
    async def test_bad_query_context(self, cb_env):
        # test w/ no context
        result = cb_env.cluster.analytics_query(f'SELECT * FROM `{cb_env.collection.name} `LIMIT 2')
        # @TODO: DatasetNotFoundException
        with pytest.raises(ParsingFailedException):
            await self.assert_rows(result, 2)

        # test w/ bad scope
        q_context = f'default:`{cb_env.bucket.name}`.`fake-scope`'
        result = self.cluster.analytics_query(
            f'SELECT * FROM `{cb_env.collection.name}` LIMIT 2', AnalyticsOptions(query_context=q_context))
        # @TODO: DataverseNotFoundException
        with pytest.raises(ParsingFailedException):
            await self.assert_rows(result, 2)

    @pytest.mark.asyncio
    async def test_scope_query(self, cb_env):
        result = cb_env.scope.analytics_query(f'SELECT * FROM `{cb_env.collection.name}` LIMIT 2')
        await self.assert_rows(result, 2)

    @pytest.mark.asyncio
    async def test_scope_query_fqdn(self, cb_env):
        # @TODO:  look into this...
        if cb_env.server_version_short >= 7.1:
            pytest.skip("Analytics scope query format not allowed on server versions >= 7.1")

        result = cb_env.scope.analytics_query(f'SELECT * FROM {cb_env.fqdn} LIMIT 2', query_context='')
        await self.assert_rows(result, 2)

    @pytest.mark.asyncio
    async def test_bad_scope_query(self, cb_env):
        scope = self.bucket.scope(self.beer_sample_collections.scope)
        q_context = f'default:`{cb_env.bucket.name}`.`fake-scope`'
        result = scope.analytics_query(f'SELECT * FROM {cb_env.fqdn} LIMIT 2',
                                       AnalyticsOptions(query_context=q_context))
        # @TODO: DataverseNotFoundException
        with pytest.raises(ParsingFailedException):
            await self.assert_rows(result, 2)

        q_context = f'default:`fake-bucket`.`{cb_env.scope.name}`'
        result = scope.analytics_query(f'SELECT * FROM {cb_env.fqdn} LIMIT 2',
                                       query_context=q_context)
        # @TODO: DataverseNotFoundException
        with pytest.raises(ParsingFailedException):
            await self.assert_rows(result, 2)

    @pytest.mark.asyncio
    async def test_scope_query_with_positional_params_in_options(self, cb_env):
        result = cb_env.scope.analytics_query(f'SELECT * FROM `{cb_env.collection.name}` WHERE country LIKE $1 LIMIT 1',
                                              AnalyticsOptions(positional_parameters=['United%']))
        await self.assert_rows(result, 1)

    @pytest.mark.asyncio
    async def test_scope_query_with_named_params_in_options(self, cb_env):
        scope = self.bucket.scope(self.beer_sample_collections.scope)
        result = scope.analytics_query(f'SELECT * FROM `{cb_env.collection.name}` WHERE country LIKE $country LIMIT 1',
                                       AnalyticsOptions(named_parameters={'country': 'United%'}))
        await self.assert_rows(result, 1)

    @pytest.mark.asyncio
    async def test_analytics_with_metrics(self, cb_env):
        initial = datetime.now()
        result = cb_env.scope.analytics_query(f'SELECT * FROM `{cb_env.collection.name}` LIMIT 1')
        await self.assert_rows(result, 1)
        taken = datetime.now() - initial
        metadata = result.metadata()  # type: AnalyticsMetaData
        metrics = metadata.metrics()
        assert isinstance(metrics, AnalyticsMetrics)
        assert isinstance(metrics.elapsed_time(), timedelta)
        assert metrics.elapsed_time() < taken
        assert metrics.elapsed_time() > timedelta(milliseconds=0)
        assert isinstance(metrics.execution_time(), timedelta)
        assert metrics.execution_time() < taken
        assert metrics.execution_time() > timedelta(milliseconds=0)

        expected_counts = {metrics.error_count: 0,
                           metrics.result_count: 1,
                           metrics.warning_count: 0}
        for method, expected in expected_counts.items():
            count_result = method()
            fail_msg = "{} failed".format(method)
            assert isinstance(count_result, UnsignedInt64), fail_msg
            assert count_result == UnsignedInt64(expected), fail_msg
        assert metrics.result_size() > UnsignedInt64(0)
        assert isinstance(metrics.processed_objects(), UnsignedInt64)
        assert metrics.error_count() == UnsignedInt64(0)

    @pytest.mark.asyncio
    async def test_analytics_metadata(self, cb_env):
        result = cb_env.scope.analytics_query(f'SELECT * FROM `{cb_env.collection.name}` LIMIT 2')
        await self.assert_rows(result, 2)
        metadata = result.metadata()  # type: AnalyticsMetaData
        assert isinstance(metadata, AnalyticsMetaData)
        for id_meth in (metadata.client_context_id, metadata.request_id):
            id_res = id_meth()
            fail_msg = "{} failed".format(id_meth)
            assert isinstance(id_res, str), fail_msg
        assert metadata.status() == AnalyticsStatus.SUCCESS
        assert isinstance(metadata.signature(), (str, dict))
        assert isinstance(metadata.warnings(), (list))
        for warning in metadata.warnings():
            assert isinstance(warning, AnalyticsWarning)
            assert isinstance(warning.message(), str)
            assert isinstance(warning.code(), int)
