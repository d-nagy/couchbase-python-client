# import pytest
import asyncio
import re
from datetime import timedelta

import pytest
import pytest_asyncio

from acouchbase.cluster import Cluster
from couchbase.auth import PasswordAuthenticator
from couchbase.exceptions import (AmbiguousTimeoutException,
                                  CouchbaseException,
                                  FeatureUnavailableException,
                                  GroupNotFoundException,
                                  InvalidArgumentException,
                                  UserNotFoundException)
from couchbase.management.collections import CollectionSpec
from couchbase.management.options import (DropUserOptions,
                                          GetUserOptions,
                                          UpsertUserOptions)
from couchbase.management.users import (Group,
                                        Role,
                                        User)
from couchbase.options import ClusterOptions

from ._test_utils import TestEnvironment


class UserManagementTests:

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
        await bucket.on_connect()
        coll = bucket.default_collection()
        cb_env = TestEnvironment(
            cluster, bucket, coll, couchbase_config, manage_users=True)

        # if cb_env.is_feature_supported('user_group_mgmt'):
        #     await cb_env.um.upsert_group(Group('test-group', roles={Role(name='admin')}))

        yield cb_env
        await cluster.close()

    @pytest.fixture(scope="class")
    def check_collections_supported(self, cb_env):
        cb_env.check_if_feature_supported('collections')

    @pytest.fixture(scope="class")
    def check_user_groups_supported(self, cb_env):
        cb_env.check_if_feature_supported('user_group_mgmt')

    @pytest.mark.asyncio
    async def test_internal_user(self, cb_env):
        """
            test_internal_user()
            Tests create, retrieve, update and removal
            of internal (domain_name="local")
            Uses *UserOptions() for options
        """

        username = 'custom-user'
        password = 's3cr3t'
        roles = [
            Role(name='data_reader', bucket='default'),
            Role(name='data_writer', bucket='default')
        ]
        initial_user = User(username=username, roles=roles, password=password)

        # create user
        await cb_env.um.upsert_user(
            User(username=username, roles=roles, password=password),
            UpsertUserOptions(domain_name="local"))

        # get user
        user_metadata = await cb_env.try_n_times(5, 1, cb_env.um.get_user, username,
                                                 GetUserOptions(domain_name="local"))

        # handle 7.0 roles w/ scopes/collections
        test_roles = roles
        if cb_env.is_feature_supported('collections'):
            test_roles = []
            for r in roles:
                test_roles.append(
                    Role(name=r.name,
                         bucket=r.bucket,
                         scope='*',
                         collection='*'))

        assert user_metadata is not None
        cb_env.validate_user_and_metadata(user_metadata, user_roles=test_roles)

        # update user
        user = user_metadata.user
        user.roles = Role('admin')
        user.password = 's3cr3t_pa33w0rd'

        await cb_env.um.upsert_user(user, UpsertUserOptions(domain_name="local"))

        # get user and verify updates
        user_metadata = await cb_env.try_n_times(5, 1, cb_env.um.get_user, username,
                                                 GetUserOptions(domain_name="local"))

        assert user_metadata is not None
        cb_env.validate_user_and_metadata(user_metadata, user_roles=user.roles)
        user_update = user_metadata.user
        assert initial_user != user_update

        # remove user
        await cb_env.um.drop_user(username, DropUserOptions(domain_name="local"))
        await cb_env.try_n_times_till_exception(
            5,
            1,
            cb_env.um.get_user,
            username,
            domain_name="local",
            expected_exceptions=UserNotFoundException)

    @pytest.mark.asyncio
    async def test_internal_user_kwargs(self, cb_env):
        """
            test_internal_user_kwargs()
            Tests create, retrieve, update and removal
            of internal (domain_name="local")
            Uses kwargs for options
        """

        username = 'custom-user'
        password = 's3cr3t'
        roles = [
            Role(name='data_reader', bucket='default'),
            Role(name='data_writer', bucket='default')
        ]
        initial_user = User(username=username, roles=roles, password=password)

        # create user
        await cb_env.um.upsert_user(initial_user, domain_name="local")

        # get single user
        user_metadata = await cb_env.try_n_times(5,
                                                 1,
                                                 cb_env.um.get_user,
                                                 username,
                                                 domain_name="local")

        # handle 7.0 roles w/ scopes/collections
        test_roles = roles
        if cb_env.is_feature_supported('collections'):
            test_roles = []
            for r in roles:
                test_roles.append(
                    Role(name=r.name,
                         bucket=r.bucket,
                         scope='*',
                         collection='*'))

        assert user_metadata is not None
        cb_env.validate_user_and_metadata(user_metadata, user_roles=test_roles)

        # update user
        user = user_metadata.user
        user.roles = Role('admin')
        user.password = 's3cr3t_pa33w0rd'

        await cb_env.um.upsert_user(user, domain_name="local")

        # get user and verify updates
        user_metadata = await cb_env.try_n_times(5,
                                                 1,
                                                 cb_env.um.get_user,
                                                 username,
                                                 domain_name="local")

        assert user_metadata is not None
        cb_env.validate_user_and_metadata(user_metadata, user_roles=user.roles)
        user_update = user_metadata.user
        assert initial_user != user_update

        # remove user
        await cb_env.um.drop_user(username, domain_name="local")
        await cb_env.try_n_times_till_exception(
            5,
            1,
            cb_env.um.get_user,
            username,
            domain_name="local",
            expected_exceptions=UserNotFoundException)

    @pytest.mark.asyncio
    async def test_internal_user_fail(self, cb_env):
        """
            test_internal_user()
            Tests create, retrieve, update and removal
            of internal (domain_name="local")
            Uses *UserOptions() for options
        """

        username = 'custom-user'
        password = 's3cr3t'
        roles = [
            Role(name='data_reader', bucket='not-a-bucket'),
            Role(name='data_writer', bucket='not-a-bucket')
        ]

        with pytest.raises(InvalidArgumentException):
            await cb_env.um.upsert_user(
                User(username=username, roles=roles, password=password),
                UpsertUserOptions(domain_name="local"))

    @pytest.mark.asyncio
    async def test_user_display_name(self, cb_env):
        roles = [
            Role(name='data_reader', bucket='default'),
            Role(name='data_writer', bucket='default')
        ]
        user = User(username='custom-user',
                    display_name="Custom User",
                    roles=roles,
                    password='s3cr3t')

        # create user
        await cb_env.um.upsert_user(user, UpsertUserOptions(domain_name="local"))

        # get user
        user_metadata = await cb_env.try_n_times(5, 1, cb_env.um.get_user,
                                                 user.username,
                                                 GetUserOptions(domain_name="local"))

        assert user_metadata.user.display_name == user.display_name

        await cb_env.um.drop_user(user.username, DropUserOptions(domain_name="local"))

    @pytest.mark.asyncio
    async def test_external_user(self, cb_env):
        """
            test_external_user()
            Tests create, retrieve, update and removal
            of external (domain_name="external")
            Uses *UserOptions() for options
        """

        username = 'custom-user'
        roles = [
            Role(name='data_reader', bucket='default'),
            Role(name='data_writer', bucket='default')
        ]
        initial_user = User(username=username, roles=roles)
        # create user
        await cb_env.um.upsert_user(initial_user,
                                    UpsertUserOptions(domain_name="external"))

        # get user
        user_metadata = await cb_env.try_n_times(
            5, 1, cb_env.um.get_user, username,
            GetUserOptions(domain_name="external"))

        # handle 7.0 roles w/ scopes/collections
        test_roles = roles
        if cb_env.is_feature_supported('collections'):
            test_roles = []
            for r in roles:
                test_roles.append(
                    Role(name=r.name,
                         bucket=r.bucket,
                         scope='*',
                         collection='*'))

        assert user_metadata is not None
        cb_env.validate_user_and_metadata(user_metadata, user_roles=test_roles)

        # update user
        user = user_metadata.user
        user.roles = Role('admin')

        await cb_env.um.upsert_user(user, UpsertUserOptions(domain_name="external"))

        # get user and verify updates
        user_metadata = await cb_env.try_n_times(
            5, 1, cb_env.um.get_user, username,
            GetUserOptions(domain_name="external"))

        assert user_metadata is not None
        cb_env.validate_user_and_metadata(user_metadata, user_roles=user.roles)
        user_update = user_metadata.user
        assert initial_user != user_update

        # remove user
        await cb_env.um.drop_user(username, DropUserOptions(domain_name="external"))
        await cb_env.try_n_times_till_exception(
            5,
            1,
            cb_env.um.get_user,
            username,
            domain_name="external",
            expected_exceptions=UserNotFoundException)

    @pytest.mark.asyncio
    async def test_default_domain(self, cb_env):

        username = 'custom-user'
        password = 's3cr3t'
        roles = [
            Role(name='data_reader', bucket='default'),
            Role(name='data_writer', bucket='default')
        ]

        await cb_env.um.upsert_user(
            User(username=username, password=password, roles=roles))

        user_metadata = await cb_env.try_n_times(5, 1, cb_env.um.get_user, username)
        assert user_metadata is not None

        # handle 7.0 roles w/ scopes/collections
        test_roles = roles
        if cb_env.is_feature_supported('collections'):
            test_roles = []
            for r in roles:
                test_roles.append(
                    Role(name=r.name,
                         bucket=r.bucket,
                         scope='*',
                         collection='*'))

        cb_env.validate_user_and_metadata(user_metadata, user_roles=test_roles)

        users_metadata = await cb_env.um.get_all_users()
        assert users_metadata is not None
        result = all(
            map(lambda um: cb_env.validate_user_and_metadata(um),
                users_metadata))
        assert result is True

        await cb_env.um.drop_user(username)

    @pytest.mark.asyncio
    async def test_invalid_domain_raises_argument_error(self, cb_env):

        username = 'custom-user'
        password = 's3cr3t'
        roles = [
            Role(name='data_reader', bucket='default'),
            Role(name='data_writer', bucket='default')
        ]

        # invalid domain generates argument error
        with pytest.raises(InvalidArgumentException):
            await cb_env.um.get_all_users(domain_name="fake-domain")

        with pytest.raises(InvalidArgumentException):
            await cb_env.um.get_user(username, domain_name="fake-domain")

        with pytest.raises(InvalidArgumentException):
            await cb_env.um.upsert_user(User(username=username,
                                             password=password,
                                             roles=roles),
                                        domain_name="fake-domain")

        with pytest.raises(InvalidArgumentException):
            await cb_env.um.drop_user(username, domain_name="fake-domain")

    @pytest.mark.asyncio
    async def test_external_nopassword(self, cb_env):

        username = 'custom-user'
        password = 's3cr3t'
        roles = [
            Role(name='data_reader', bucket='default'),
            Role(name='data_writer', bucket='default')
        ]

        # password with external generates argument error
        with pytest.raises(InvalidArgumentException):
            await cb_env.um.upsert_user(User(username=username,
                                             password=password,
                                             roles=roles),
                                        domain_name="external")

        with pytest.raises(InvalidArgumentException):
            await cb_env.um.upsert_user(User(username=username,
                                             password=password,
                                             roles=None),
                                        domain_name="external")

        with pytest.raises(InvalidArgumentException):
            await cb_env.um.upsert_user(User(username=username, password=password, roles=[]),
                                        domain_name="external")
        try:
            await cb_env.um.upsert_user(
                User(username=username, password=None, roles=roles),
                UpsertUserOptions(domain_name="external"))
        except InvalidArgumentException:
            raise
        except CouchbaseException:
            pass
        finally:
            await cb_env.um.drop_user(username, domain_name="external")

    @pytest.mark.usefixtures("check_collections_supported")
    @pytest.mark.asyncio
    async def test_user_scopes_collections(self, cb_env):

        if cb_env.cm is None:
            cm = cb_env.bucket.collections()

        await cm.create_scope('um-test-scope')
        for _ in range(3):
            scopes = await cm.get_all_scopes()
            scope = next((s for s in scopes if s.name == 'um-test-scope'), None)
            if scope:
                break
            await asyncio.sleep(1)

        collection = CollectionSpec('test-collection', scope_name='um-test-scope')
        await cm.create_collection(collection)
        for _ in range(3):
            scopes = await cm.get_all_scopes()
            scope = next((s for s in scopes if s.name == 'um-test-scope'), None)
            if scope:
                coll = next((c for c in scope.collections
                             if c.name == 'test-collection'), None)
                if coll:
                    break
            await asyncio.sleep(1)

        username = 'custom-user'
        password = 's3cr3t'
        roles = [
            Role(name='data_reader', bucket='default', scope='um-test-scope'),
            Role(name='data_writer',
                 bucket='default',
                 scope='um-test-scope',
                 collection='test-collection')
        ]
        initial_user = User(username=username, roles=roles, password=password)

        # create user
        await cb_env.um.upsert_user(initial_user, domain_name="local")

        # get single user
        user_metadata = await cb_env.try_n_times(5,
                                                 1,
                                                 cb_env.um.get_user,
                                                 username,
                                                 domain_name="local")

        test_roles = []
        for r in roles:
            if not r.collection:
                test_roles.append(
                    Role(name=r.name,
                         bucket=r.bucket,
                         scope=r.scope,
                         collection='*'))
            else:
                test_roles.append(r)

        assert user_metadata is not None
        cb_env.validate_user_and_metadata(user_metadata, user_roles=test_roles)

        await cb_env.um.drop_user(username)
        await cm.drop_collection(collection)
        await cm.drop_scope('um-test-scope')

    @pytest.mark.asyncio
    async def test_group_feature_not_found(self, cb_env):
        if cb_env.is_feature_supported('user_group_mgmt'):
            pytest.skip("Only test on Server Versions < 6.5")

        roles = Role(name='admin')
        test_group = Group(name='my-test-group',
                           roles=roles,
                           description="test group description")

        with pytest.raises(FeatureUnavailableException):
            await self.um.upsert_group(test_group)
        with pytest.raises(FeatureUnavailableException):
            await self.um.get_all_groups()
        with pytest.raises(FeatureUnavailableException):
            await self.um.get_group(test_group.name)
        with pytest.raises(FeatureUnavailableException):
            await self.um.drop_group(test_group.name)

    @pytest.mark.usefixtures("check_user_groups_supported")
    @pytest.mark.asyncio
    async def test_group(self, cb_env):
        roles = Role(name='admin')
        test_group = Group(name='my-test-group',
                           roles=roles,
                           description="test group description")
        # add group
        await cb_env.um.upsert_group(test_group)

        # get group
        result = await cb_env.try_n_times(5, 1, cb_env.um.get_group, test_group.name)
        cb_env.validate_group(result, test_group.roles)

        # remove group
        await cb_env.um.drop_group(test_group.name)
        await cb_env.try_n_times_till_exception(
            5,
            1,
            cb_env.um.get_group,
            test_group.name,
            expected_exceptions=GroupNotFoundException)

    @pytest.mark.usefixtures("check_user_groups_supported")
    @pytest.mark.asyncio
    async def test_user_and_groups(self, cb_env):
        user_roles = [
            Role(name='query_select', bucket='default'),
            Role(name='fts_searcher', bucket='default')
        ]
        group_roles = [
            Role(name='data_reader', bucket='*'),
            Role(name='data_writer', bucket='*')
        ]
        groups = [
            Group(name='my-test-group',
                  roles=group_roles,
                  description="test group description"),
            Group(name='my-test-group-1',
                  roles=Role(name='admin'),
                  description="test group description")
        ]

        # add groups
        for group in groups:
            await cb_env.um.upsert_group(group)
            await cb_env.try_n_times(5, 1, cb_env.um.get_group, group.name)
        user_groups = list(map(lambda g: g.name, groups))

        # add user
        test_user = User(username='custom-user',
                         roles=user_roles,
                         groups=user_groups,
                         password='s3cr3t')
        await cb_env.um.upsert_user(test_user, domain_name="local")

        # get user
        user_metadata = await cb_env.try_n_times(5,
                                                 1,
                                                 cb_env.um.get_user,
                                                 test_user.username,
                                                 domain_name="local")

        # handle 7.0 roles w/ scopes/collections
        test_roles = user_roles
        if cb_env.is_feature_supported('collections'):
            test_roles = []
            for r in user_roles:
                test_roles.append(
                    Role(name=r.name,
                         bucket=r.bucket,
                         scope='*',
                         collection='*'))

        assert user_metadata is not None
        cb_env.validate_user_and_metadata(user_metadata,
                                          user_roles=test_roles,
                                          groups=groups)

        # remove group
        remove_group = groups.pop()
        await cb_env.um.drop_group(remove_group.name)
        await cb_env.try_n_times_till_exception(
            5,
            1,
            cb_env.um.get_group,
            remove_group.name,
            expected_exceptions=GroupNotFoundException)

        # get user to verify roles from removed group are removed
        user_metadata = await cb_env.try_n_times(5,
                                                 1,
                                                 cb_env.um.get_user,
                                                 test_user.username,
                                                 domain_name="local")

        # handle 7.0 roles w/ scopes/collections
        if cb_env.is_feature_supported('collections'):
            test_roles = []
            for r in user_roles:
                test_roles.append(
                    Role(name=r.name,
                         bucket=r.bucket,
                         scope='*',
                         collection='*'))
        assert user_metadata is not None
        cb_env.validate_user_and_metadata(user_metadata,
                                          user_roles=test_roles,
                                          groups=groups)

        # cleanup
        await cb_env.um.drop_user(test_user.username, domain_name="local")
        for group in groups:
            await cb_env.um.drop_group(group.name)

    @pytest.mark.usefixtures("check_user_groups_supported")
    @pytest.mark.asyncio
    async def test_get_all_groups(self, cb_env):
        roles = [
            Role(name='data_reader', bucket='*'),
            Role(name='data_writer', bucket='*')
        ]
        fresh_group = Group(name='my-test-group',
                            roles=roles,
                            description="test group description")
        await cb_env.um.upsert_group(fresh_group)
        admin_group = Group('admin-test-group', roles=[Role(name='admin')])
        await cb_env.um.upsert_group(admin_group)
        all_groups = await cb_env.um.get_all_groups()
        # NOTE: we could well have other groups on this server, apart from the one we added, so
        # lets be ok with there being more of them.  However, the one we added
        # _MUST_ be there.
        assert len(all_groups) >= 2
        admin_group_dict = admin_group.as_dict()
        found = False
        for g in all_groups:
            if admin_group_dict == g.as_dict():
                found = True

        await cb_env.um.drop_group('my-test-group')
        await cb_env.um.drop_group('admin-test-group')
        assert found is True

    @pytest.mark.usefixtures("check_user_groups_supported")
    @pytest.mark.asyncio
    async def test_timeout(self, cb_env):
        with pytest.raises(AmbiguousTimeoutException):
            await cb_env.um.get_all_groups(timeout=timedelta(seconds=0.1))

    @pytest.mark.asyncio
    async def test_get_roles(self, cb_env):
        roles = await cb_env.um.get_roles()
        admin_desc = re.compile(
            r'.*all cluster features.*web console.*read and write all data.*$')
        for rad in reversed(roles):
            desc_matches = admin_desc.match(rad.description)
            if desc_matches:
                assert rad.role.name == 'admin'
                assert rad.display_name == 'Full Admin'
                return
        pytest.fail("No admin role found")

    # see PYCBC-1030
    @pytest.mark.asyncio
    async def test_get_roles_all_valid(self, cb_env):
        roles = await cb_env.um.get_roles()
        for r in roles:
            assert r is not None

    @pytest.mark.usefixtures("check_user_groups_supported")
    @pytest.mark.asyncio
    async def test_missing_group(self, cb_env):
        with pytest.raises(GroupNotFoundException):
            await cb_env.um.get_group('fred')

    @pytest.mark.asyncio
    async def test_missing_user(self, cb_env):
        with pytest.raises(UserNotFoundException):
            await cb_env.um.get_user('keith')
