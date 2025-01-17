import pytest

from couchbase.auth import PasswordAuthenticator
from couchbase.cluster import Cluster
from couchbase.exceptions import DocumentNotFoundException, InvalidArgumentException
from couchbase.options import (ClusterOptions,
                               DecrementOptions,
                               DeltaValue,
                               IncrementOptions,
                               SignedInt64)
from couchbase.result import CounterResult, MutationResult
from couchbase.transcoder import RawBinaryTranscoder, RawStringTranscoder

from ._test_utils import (CollectionType,
                          KVPair,
                          TestEnvironment)


class BinaryCollectionTests:

    @pytest.fixture(scope="class", name="cb_env", params=[CollectionType.DEFAULT, CollectionType.NAMED])
    def couchbase_test_environment(self, couchbase_config, request):
        conn_string = couchbase_config.get_connection_string()
        username, pw = couchbase_config.get_username_and_pw()
        opts = ClusterOptions(PasswordAuthenticator(username, pw))
        cluster = Cluster(
            conn_string, opts)
        cluster.cluster_info()
        bucket = cluster.bucket(f"{couchbase_config.bucket_name}")
        coll = bucket.default_collection()
        if request.param == CollectionType.DEFAULT:
            cb_env = TestEnvironment(cluster, bucket, coll, couchbase_config, manage_buckets=True)
        elif request.param == CollectionType.NAMED:
            cb_env = TestEnvironment(cluster, bucket, coll, couchbase_config,
                                     manage_buckets=True, manage_collections=True)
            cb_env.setup_named_collections()

        yield cb_env

        # teardown
        # cb_env.purge_binary_data()
        if request.param == CollectionType.NAMED:
            cb_env.teardown_named_collections()
        cluster.close()

    # key/value fixtures

    @pytest.fixture(name='utf8_empty_kvp')
    def utf8_key_and_empty_value(self, cb_env) -> KVPair:
        key, value = cb_env.load_utf8_binary_data()
        yield KVPair(key, value)
        cb_env.collection.upsert(key, '', transcoder=RawStringTranscoder())

    @pytest.fixture(name='utf8_kvp')
    def utf8_key_and_value(self, cb_env) -> KVPair:
        key, value = cb_env.load_utf8_binary_data(start_value='XXXX')
        yield KVPair(key, value)
        cb_env.collection.upsert(key, '', transcoder=RawStringTranscoder())

    @pytest.fixture(name='bytes_empty_kvp')
    def bytes_key_and_empty_value(self, cb_env) -> KVPair:
        key, value = cb_env.load_bytes_binary_data()
        yield KVPair(key, value)
        cb_env.collection.upsert(key, b'', transcoder=RawBinaryTranscoder())

    @pytest.fixture(name='bytes_kvp')
    def bytes_key_and_value(self, cb_env) -> KVPair:
        key, value = cb_env.load_bytes_binary_data(start_value=b'XXXX')
        yield KVPair(key, value)
        cb_env.collection.upsert(key, b'', transcoder=RawBinaryTranscoder())

    @pytest.fixture(name='counter_empty_kvp')
    def counter_key_and_empty_value(self, cb_env) -> KVPair:
        key, value = cb_env.load_counter_binary_data()
        yield KVPair(key, value)
        cb_env.try_n_times_till_exception(10,
                                          1,
                                          cb_env.collection.remove,
                                          key,
                                          expected_exceptions=(DocumentNotFoundException,))

    @pytest.fixture(name='counter_kvp')
    def counter_key_and_value(self, cb_env) -> KVPair:
        key, value = cb_env.load_counter_binary_data(start_value=100)
        yield KVPair(key, value)
        cb_env.try_n_times_till_exception(10,
                                          1,
                                          cb_env.collection.remove,
                                          key,
                                          expected_exceptions=(DocumentNotFoundException,))

    # tests

    def test_append_string(self, cb_env, utf8_empty_kvp):
        cb = cb_env.collection
        key = utf8_empty_kvp.key
        result = cb.binary().append(key, 'foo')
        assert isinstance(result, MutationResult)
        assert result.cas is not None
        # make sure it really worked
        result = cb.get(key, transcoder=RawStringTranscoder())
        assert result.content_as[str] == 'foo'

    def test_append_string_not_empty(self, cb_env, utf8_kvp):
        cb = cb_env.collection
        key = utf8_kvp.key
        value = utf8_kvp.value
        result = cb.binary().append(key, 'foo')
        assert isinstance(result, MutationResult)
        assert result.cas is not None
        result = cb.get(key, transcoder=RawStringTranscoder())
        assert result.content_as[str] == value + 'foo'

    def test_append_string_nokey(self, cb_env, utf8_empty_kvp):
        cb = cb_env.collection
        key = utf8_empty_kvp.key
        cb.remove(key)
        cb_env.try_n_times_till_exception(10,
                                          1,
                                          cb.get,
                                          key,
                                          expected_exceptions=(DocumentNotFoundException,))

        # @TODO(jc):  3.2.x SDK tests for NotStoredException
        with pytest.raises(DocumentNotFoundException):
            cb.binary().append(key, 'foo')

    def test_append_bytes(self, cb_env, bytes_empty_kvp):
        cb = cb_env.collection
        key = bytes_empty_kvp.key
        result = cb.binary().append(key, b'XXX')
        assert isinstance(result, MutationResult)
        assert result.cas is not None
        # make sure it really worked
        result = cb.get(key, transcoder=RawBinaryTranscoder())
        assert result.content_as[bytes] == b'XXX'

    def test_append_bytes_not_empty(self, cb_env, bytes_kvp):
        cb = cb_env.collection
        key = bytes_kvp.key
        value = bytes_kvp.value

        result = cb.binary().append(key, 'foo')
        assert isinstance(result, MutationResult)
        assert result.cas is not None
        result = cb.get(key, transcoder=RawBinaryTranscoder())
        assert result.content_as[bytes] == value + b'foo'

    def test_prepend_string(self, cb_env, utf8_empty_kvp):
        cb = cb_env.collection
        key = utf8_empty_kvp.key
        result = cb.binary().prepend(key, 'foo')
        assert isinstance(result, MutationResult)
        assert result.cas is not None
        # make sure it really worked
        result = cb.get(key, transcoder=RawStringTranscoder())
        assert result.content_as[str] == 'foo'

    def test_prepend_string_not_empty(self, cb_env, utf8_kvp):
        cb = cb_env.collection
        key = utf8_kvp.key
        value = utf8_kvp.value

        result = cb.binary().prepend(key, 'foo')
        assert isinstance(result, MutationResult)
        assert result.cas is not None
        result = cb.get(key, transcoder=RawStringTranscoder())
        assert result.content_as[str] == 'foo' + value

    def test_prepend_string_nokey(self, cb_env, utf8_empty_kvp):
        cb = cb_env.collection
        key = utf8_empty_kvp.key
        cb.remove(key)
        cb_env.try_n_times_till_exception(10,
                                          1,
                                          cb.get,
                                          key,
                                          expected_exceptions=(DocumentNotFoundException,))

        # @TODO(jc):  3.2.x SDK tests for NotStoredException
        with pytest.raises(DocumentNotFoundException):
            cb.binary().prepend(key, 'foo')

    def test_prepend_bytes(self, cb_env, bytes_empty_kvp):
        cb = cb_env.collection
        key = bytes_empty_kvp.key
        result = cb.binary().prepend(key, b'XXX')
        assert isinstance(result, MutationResult)
        assert result.cas is not None
        # make sure it really worked
        result = cb.get(key, transcoder=RawBinaryTranscoder())
        assert result.content_as[bytes] == b'XXX'

    def test_prepend_bytes_not_empty(self, cb_env, bytes_kvp):
        cb = cb_env.collection
        key = bytes_kvp.key
        value = bytes_kvp.value

        result = cb.binary().prepend(key, b'foo')
        assert isinstance(result, MutationResult)
        assert result.cas is not None
        result = cb.get(key, transcoder=RawBinaryTranscoder())
        assert result.content_as[bytes] == b'foo' + value

    def test_counter_increment_initial_value(self, cb_env, counter_empty_kvp):
        cb = cb_env.collection
        key = counter_empty_kvp.key

        result = cb.binary().increment(key, IncrementOptions(initial=SignedInt64(100)))
        assert isinstance(result, CounterResult)
        assert result.cas is not None
        assert result.content == 100

    def test_counter_decrement_initial_value(self, cb_env, counter_empty_kvp):
        cb = cb_env.collection
        key = counter_empty_kvp.key

        result = cb.binary().decrement(key, DecrementOptions(initial=SignedInt64(100)))
        assert isinstance(result, CounterResult)
        assert result.cas is not None
        assert result.content == 100

    def test_counter_increment(self, cb_env, counter_kvp):
        cb = cb_env.collection
        key = counter_kvp.key
        value = counter_kvp.value

        result = cb.binary().increment(key)
        assert isinstance(result, CounterResult)
        assert result.cas is not None
        assert result.content == value + 1

    def test_counter_decrement(self, cb_env, counter_kvp):
        cb = cb_env.collection
        key = counter_kvp.key
        value = counter_kvp.value

        result = cb.binary().decrement(key)
        assert isinstance(result, CounterResult)
        assert result.cas is not None
        assert result.content == value - 1

    def test_counter_increment_non_default(self, cb_env, counter_kvp):
        cb = cb_env.collection
        key = counter_kvp.key
        value = counter_kvp.value

        result = cb.binary().increment(key, IncrementOptions(delta=DeltaValue(3)))
        assert isinstance(result, CounterResult)
        assert result.cas is not None
        assert result.content == value + 3

    def test_counter_decrement_non_default(self, cb_env, counter_kvp):
        cb = cb_env.collection
        key = counter_kvp.key
        value = counter_kvp.value

        result = cb.binary().decrement(key, DecrementOptions(delta=DeltaValue(3)))
        assert isinstance(result, CounterResult)
        assert result.cas is not None
        assert result.content == value - 3

    def test_counter_bad_initial_value(self, cb_env, counter_empty_kvp):
        cb = cb_env.collection
        key = counter_empty_kvp.key

        with pytest.raises(InvalidArgumentException):
            cb.binary().increment(key, initial=100)

        with pytest.raises(InvalidArgumentException):
            cb.binary().decrement(key, initial=100)

    def test_counter_bad_delta_value(self, cb_env, counter_empty_kvp):
        cb = cb_env.collection
        key = counter_empty_kvp.key

        with pytest.raises(InvalidArgumentException):
            cb.binary().increment(key, delta=5)

        with pytest.raises(InvalidArgumentException):
            cb.binary().decrement(key, delta=5)

    def test_unsigned_int(self):
        with pytest.raises(InvalidArgumentException):
            x = DeltaValue(-1)
        with pytest.raises(InvalidArgumentException):
            x = DeltaValue(0x7FFFFFFFFFFFFFFF + 1)

        x = DeltaValue(5)
        assert 5 == x.value

    def test_signed_int_64(self):
        with pytest.raises(InvalidArgumentException):
            x = SignedInt64(-0x7FFFFFFFFFFFFFFF - 2)

        with pytest.raises(InvalidArgumentException):
            x = SignedInt64(0x7FFFFFFFFFFFFFFF + 1)

        x = SignedInt64(0x7FFFFFFFFFFFFFFF)
        assert 0x7FFFFFFFFFFFFFFF == x.value
        x = SignedInt64(-0x7FFFFFFFFFFFFFFF - 1)
        assert -0x7FFFFFFFFFFFFFFF - 1 == x.value
