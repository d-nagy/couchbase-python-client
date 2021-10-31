import asyncio
from unittest import SkipTest
from functools import wraps
import re
from datetime import timedelta, datetime

from acouchbase.cluster import (Cluster, get_event_loop,
                                close_event_loop)
from couchbase_tests.async_base import AsyncioTestCase, async_test
from couchbase.exceptions import (BucketDoesNotExistException, FeatureNotFoundException,
                                  InvalidArgumentException)
from couchbase.management.users import (DropUserOptions, GetUserOptions, Role,
                                        RoleAndOrigins, UpsertUserOptions, User,
                                        GroupNotFoundException, UserNotFoundException, Group)
from couchbase.auth import AuthDomain
from couchbase.management.buckets import CreateBucketSettings
from couchbase.management.collections import CollectionSpec


def skip_if_no_groups_async(func):
    @wraps(func)
    async def wrap(self, *args, **kwargs):
        if not await self._supports_groups():
            raise SkipTest('groups not supported (server < 6.5?)')
        await func(self, *args, **kwargs)

    return wrap


class AcouchbaseUserManagerTests(AsyncioTestCase):

    @classmethod
    def setUpClass(cls) -> None:
        super(AcouchbaseUserManagerTests, cls).setUpClass(
            get_event_loop(), cluster_class=Cluster)

    @classmethod
    def tearDownClass(cls) -> None:
        super(AcouchbaseUserManagerTests, cls).tearDownClass()
        close_event_loop()

    def setUp(self):
        super(AcouchbaseUserManagerTests, self).setUp()
        if self.is_mock:
            raise SkipTest("Real server must be used for admin tests")

        self.bm = self.cluster.buckets()
        self.loop.run_until_complete(self._initialize())

    def tearDown(self):
        self.loop.run_until_complete(self._tear_down())
        super(AcouchbaseUserManagerTests, self).tearDown()

    async def _initialize(self):
        try:
            self.test_bucket = await self.bm.get_bucket("default")
        except BucketDoesNotExistException:
            await self.bm.create_bucket(
                CreateBucketSettings(name="default",
                                     bucket_type="couchbase",
                                     ram_quota_mb=100))

        self.um = self.cluster.users()
        if await self._supports_groups():
            await self.um.upsert_group(Group('qweqwe', roles={Role(name='admin')}))

    async def _tear_down(self):
        if await self._supports_groups():
            await self.um.drop_group('qweqwe')

    async def _supports_groups(self):
        # mock doesnt support it
        if self.is_mock:
            return False
        # get_all_groups will raise NotSupported when we are hiting < 6.5
        try:
            await self.um.get_all_groups()
            return True
        except FeatureNotFoundException:
            return False

    def validate_user(self, user, user_roles=None):
        #password is write-only
        property_list = ['username', 'groups', 'roles']
        properties = list(n for n in dir(user) if n in property_list)
        for p in properties:
            value = getattr(user, p)
            if p == 'username':
                self.assertIsNotNone(value)
            elif p == 'groups' and value:
                self.assertIsInstance(value, set)
                if len(value) > 0:
                    self.assertTrue(
                        all(map(lambda r: isinstance(r, str), value)))
            elif p == 'roles':
                self.assertIsInstance(value, set)
                if len(value) > 0:
                    self.assertTrue(
                        all(map(lambda r: isinstance(r, Role), value)))

        if user_roles:
            self.assertEqual(len(user_roles), len(user.roles))
            self.assertEqual(set(user_roles), user.roles)

        return True

    def validate_user_and_metadata(self,
                                   user_metadata,
                                   user_roles=None,
                                   groups=None):
        property_list = [
            'domain', 'user', 'effective_roles', 'password_changed',
            'external_groups'
        ]
        properties = list(n for n in dir(user_metadata) if n in property_list)
        for p in properties:
            value = getattr(user_metadata, p)
            if p == 'domain':
                self.assertIsInstance(value, AuthDomain)
            elif p == 'user':
                self.assertIsInstance(value, User)
                # per RFC, user property should return a mutable User object
                #   that will not have an effect on the UserAndMetadata object
                self.assertNotEqual(id(value), id(user_metadata._user))
                self.validate_user(value, user_roles)
            elif p == 'effective_roles':
                self.assertIsInstance(value, list)
                if len(value) > 0:
                    self.assertTrue(
                        all(map(lambda r: isinstance(r, RoleAndOrigins),
                                value)))
            elif p == 'password_changed' and value:
                self.assertIsInstance(value, datetime)
            elif p == 'external_groups' and value:
                self.assertIsInstance(value, set)
                if len(value) > 0:
                    self.assertTrue(
                        all(map(lambda r: isinstance(r, str), value)))

        if user_roles:
            actual_roles = set(
                r.role for r in user_metadata.effective_roles
                if any(map(lambda o: o.type == 'user', r.origins))
                or len(r.origins) == 0)
            self.assertEqual(len(user_roles), len(actual_roles))
            #actual_roles = set(map(lambda r: r.role, user_metadata.effective_roles))
            self.assertEqual(set(user_roles), actual_roles)

        if groups:
            actual_roles = set(
                r.role for r in user_metadata.effective_roles
                if any(map(lambda o: o.type != 'user', r.origins)))
            group_roles = set()
            for g in groups:
                group_roles.update(g.roles)

            self.assertEqual(len(group_roles), len(actual_roles))

        return True

    def validate_group(self, group, roles=None):
        property_list = [
            'name', 'description', 'roles', 'ldap_group_reference'
        ]
        properties = list(n for n in dir(group) if n in property_list)
        for p in properties:
            value = getattr(group, p)
            if p == 'name':
                self.assertIsNotNone(value)
            elif p == 'description' and value:
                self.assertIsInstance(value, str)
            elif p == 'roles':
                self.assertIsInstance(value, set)
                if len(value) > 0:
                    self.assertTrue(
                        all(map(lambda r: isinstance(r, Role), value)))
            elif p == 'ldap_group_reference' and value:
                self.assertIsInstance(value, str)

        if roles:
            self.assertEqual(len(roles), len(group.roles))
            self.assertEqual(set(roles), group.roles)

        return True

    @async_test
    async def test_internal_user(self):
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
        await self.um.upsert_user(
            User(username=username, roles=roles, password=password),
            UpsertUserOptions(domain_name="local"))

        # get user
        user_metadata = await self.try_n_times_async(10, 1, self.um.get_user, username,
                                                     GetUserOptions(domain_name="local"))

        # handle 7.0 roles w/ scopes/collections
        test_roles = roles
        if self.supports_collections():
            test_roles = []
            for r in roles:
                test_roles.append(
                    Role(name=r.name,
                         bucket=r.bucket,
                         scope='*',
                         collection='*'))

        self.assertIsNotNone(user_metadata)
        self.validate_user_and_metadata(user_metadata, user_roles=test_roles)

        # update user
        user = user_metadata.user
        user.roles = Role('admin')
        user.password = 's3cr3t_pa33w0rd'

        await self.um.upsert_user(user, UpsertUserOptions(domain_name="local"))

        # get user and verify updates
        user_metadata = await self.try_n_times_async(10, 1, self.um.get_user, username,
                                                     GetUserOptions(domain_name="local"))

        self.assertIsNotNone(user_metadata)
        self.validate_user_and_metadata(user_metadata, user_roles=user.roles)
        user_update = user_metadata.user
        self.assertNotEqual(initial_user, user_update)

        # remove user
        await self.um.drop_user(username, DropUserOptions(domain_name="local"))
        await self.try_n_times_till_exception_async(
            10,
            1,
            self.um.get_user,
            username,
            domain_name="local",
            expected_exceptions=UserNotFoundException)

    @async_test
    async def test_internal_user_kwargs(self):
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
        await self.um.upsert_user(initial_user, domain_name="local")

        # get single user
        user_metadata = await self.try_n_times_async(10,
                                                     1,
                                                     self.um.get_user,
                                                     username,
                                                     domain_name="local")

        # handle 7.0 roles w/ scopes/collections
        test_roles = roles
        if self.supports_collections():
            test_roles = []
            for r in roles:
                test_roles.append(
                    Role(name=r.name,
                         bucket=r.bucket,
                         scope='*',
                         collection='*'))

        self.assertIsNotNone(user_metadata)
        self.validate_user_and_metadata(user_metadata, user_roles=test_roles)

        # update user
        user = user_metadata.user
        user.roles = Role('admin')
        user.password = 's3cr3t_pa33w0rd'

        await self.um.upsert_user(user, domain_name="local")

        # get user and verify updates
        user_metadata = await self.try_n_times_async(10,
                                                     1,
                                                     self.um.get_user,
                                                     username,
                                                     domain_name="local")

        self.assertIsNotNone(user_metadata)
        self.validate_user_and_metadata(user_metadata, user_roles=user.roles)
        user_update = user_metadata.user
        self.assertNotEqual(initial_user, user_update)

        # remove user
        await self.um.drop_user(username, domain_name="local")
        await self.try_n_times_till_exception_async(
            10,
            1,
            self.um.get_user,
            username,
            domain_name="local",
            expected_exceptions=UserNotFoundException)

    @async_test
    async def test_user_display_name(self):
        roles = [
            Role(name='data_reader', bucket='default'),
            Role(name='data_writer', bucket='default')
        ]
        user = User(username='custom-user',
                    display_name="Custom User",
                    roles=roles,
                    password='s3cr3t')

        # create user
        await self.um.upsert_user(user, UpsertUserOptions(domain_name="local"))

        # get user
        user_metadata = await self.try_n_times_async(10, 1, self.um.get_user,
                                                     user.username,
                                                     GetUserOptions(domain_name="local"))

        self.assertEquals(user_metadata.user.display_name, user.display_name)

        await self.um.drop_user(user.username, DropUserOptions(domain_name="local"))

    @async_test
    async def test_external_user(self):
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
        await self.um.upsert_user(initial_user,
                                  UpsertUserOptions(domain_name="external"))

        # get user
        user_metadata = await self.try_n_times_async(
            10, 1, self.um.get_user, username,
            GetUserOptions(domain_name="external"))

        # handle 7.0 roles w/ scopes/collections
        test_roles = roles
        if self.supports_collections():
            test_roles = []
            for r in roles:
                test_roles.append(
                    Role(name=r.name,
                         bucket=r.bucket,
                         scope='*',
                         collection='*'))

        self.assertIsNotNone(user_metadata)
        self.validate_user_and_metadata(user_metadata, user_roles=test_roles)

        # update user
        user = user_metadata.user
        user.roles = Role('admin')

        await self.um.upsert_user(user, UpsertUserOptions(domain_name="external"))

        # get user and verify updates
        user_metadata = await self.try_n_times_async(
            10, 1, self.um.get_user, username,
            GetUserOptions(domain_name="external"))

        self.assertIsNotNone(user_metadata)
        self.validate_user_and_metadata(user_metadata, user_roles=user.roles)
        user_update = user_metadata.user
        self.assertNotEqual(initial_user, user_update)

        # remove user
        await self.um.drop_user(username, DropUserOptions(domain_name="external"))
        await self.try_n_times_till_exception_async(
            10,
            1,
            self.um.get_user,
            username,
            domain_name="external",
            expected_exceptions=UserNotFoundException)

    @async_test
    async def test_default_domain(self):

        username = 'custom-user'
        password = 's3cr3t'
        roles = [
            Role(name='data_reader', bucket='default'),
            Role(name='data_writer', bucket='default')
        ]

        await self.um.upsert_user(
            User(username=username, password=password, roles=roles))

        user_metadata = await self.try_n_times_async(10, 1, self.um.get_user, username)
        self.assertIsNotNone(user_metadata)

        # handle 7.0 roles w/ scopes/collections
        test_roles = roles
        if self.supports_collections():
            test_roles = []
            for r in roles:
                test_roles.append(
                    Role(name=r.name,
                         bucket=r.bucket,
                         scope='*',
                         collection='*'))

        self.validate_user_and_metadata(user_metadata, user_roles=test_roles)

        users_metadata = await self.um.get_all_users()
        self.assertIsNotNone(users_metadata)
        result = all(
            map(lambda um: self.validate_user_and_metadata(um),
                users_metadata))
        self.assertTrue(result)

        await self.um.drop_user(username)

    @async_test
    async def test_invalid_domain_raises_argument_error(self):

        username = 'custom-user'
        password = 's3cr3t'
        roles = [
            Role(name='data_reader', bucket='default'),
            Role(name='data_writer', bucket='default')
        ]

        # invalid domain generates argument error
        with self.assertRaises(InvalidArgumentException):
            await self.um.get_all_users(domain_name="fake-domain")

        with self.assertRaises(InvalidArgumentException):
            await self.um.get_user(username, domain_name="fake-domain")

        with self.assertRaises(InvalidArgumentException):
            await self.um.upsert_user(User(username=username,
                                           password=password,
                                           roles=roles),
                                      domain_name="fake-domain")

        with self.assertRaises(InvalidArgumentException):
            await self.um.drop_user(username, domain_name="fake-domain")

    @async_test
    async def test_external_nopassword(self):

        username = 'custom-user'
        password = 's3cr3t'
        roles = [
            Role(name='data_reader', bucket='default'),
            Role(name='data_writer', bucket='default')
        ]

        # password with external generates argument error
        with self.assertRaises(InvalidArgumentException):
            await self.um.upsert_user(User(username=username,
                                           password=password,
                                           roles=roles),
                                      domain_name="external")

        with self.assertRaises(InvalidArgumentException):
            await self.um.upsert_user(User(username=username,
                                           password=password,
                                           roles=None),
                                      domain_name="external")

        with self.assertRaises(InvalidArgumentException):
            await self.um.upsert_user(User(username=username, password=password, roles=[]),
                                      domain_name="external")
        try:
            await self.um.upsert_user(
                User(username=username, password=None, roles=roles),
                UpsertUserOptions(domain_name="external"))
        except InvalidArgumentException:
            raise
        except BaseException:
            pass
        finally:
            await self.um.drop_user(username, domain_name="external")

    @async_test
    async def test_user_scopes_collections(self):
        if not self.supports_collections():
            raise SkipTest('Only test on Server >= 7.0')

        async def get_bucket(name):
            b = self.cluster.bucket(name)
            await b.on_connect()
            return b

        test_bucket = await self.try_n_times_async(10, 3, get_bucket, 'default')
        cm = test_bucket.collections()

        await cm.create_scope('test-scope')
        for _ in range(3):
            scopes = await cm.get_all_scopes()
            scope = next((s for s in scopes if s.name == 'test-scope'), None)
            if scope:
                break
            await asyncio.sleep(1)

        collection = CollectionSpec('test-collection', scope_name='test-scope')
        await cm.create_collection(collection)
        for _ in range(3):
            scopes = await cm.get_all_scopes()
            scope = next((s for s in scopes if s.name == 'test-scope'), None)
            if scope:
                coll = next((c for c in scope.collections
                             if c.name == 'test-collection'), None)
                if coll:
                    break
            await asyncio.sleep(1)

        username = 'custom-user'
        password = 's3cr3t'
        roles = [
            Role(name='data_reader', bucket='default', scope='test-scope'),
            Role(name='data_writer',
                 bucket='default',
                 scope='test-scope',
                 collection='test-collection')
        ]
        initial_user = User(username=username, roles=roles, password=password)

        # create user
        await self.um.upsert_user(initial_user, domain_name="local")

        # get single user
        user_metadata = await self.try_n_times_async(10,
                                                     1,
                                                     self.um.get_user,
                                                     username,
                                                     domain_name="local")

        # handle 7.0 roles w/ scopes/collections
        test_roles = roles
        if self.supports_collections():
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

        self.assertIsNotNone(user_metadata)
        self.validate_user_and_metadata(user_metadata, user_roles=test_roles)

        await self.um.drop_user(username)
        await cm.drop_collection(collection)
        await cm.drop_scope('test-scope')

    @async_test
    async def test_group_feature_not_found(self):
        if await self._supports_groups():
            raise SkipTest('Only test on Server < 6.5')

        roles = Role(name='admin')
        test_group = Group(name='my-test-group',
                           roles=roles,
                           description="test group description")

        with self.assertRaises(FeatureNotFoundException):
            await self.um.upsert_group(test_group)
        with self.assertRaises(FeatureNotFoundException):
            await self.um.get_all_groups()
        with self.assertRaises(FeatureNotFoundException):
            await self.um.get_group(test_group.name)
        with self.assertRaises(FeatureNotFoundException):
            await self.um.drop_group(test_group.name)

    @async_test
    @skip_if_no_groups_async
    async def test_group(self):
        roles = Role(name='admin')
        test_group = Group(name='my-test-group',
                           roles=roles,
                           description="test group description")
        # add group
        await self.um.upsert_group(test_group)

        # get group
        result = await self.try_n_times_async(10, 1, self.um.get_group, test_group.name)
        self.validate_group(result, test_group.roles)

        # remove group
        await self.um.drop_group(test_group.name)
        await self.try_n_times_till_exception_async(
            10,
            1,
            self.um.get_group,
            test_group.name,
            expected_exceptions=GroupNotFoundException)

    @async_test
    @skip_if_no_groups_async
    async def test_user_and_groups(self):
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
            await self.um.upsert_group(group)
            await self.try_n_times_async(10, 1, self.um.get_group, group.name)
        user_groups = list(map(lambda g: g.name, groups))

        # add user
        test_user = User(username='custom-user',
                         roles=user_roles,
                         groups=user_groups,
                         password='s3cr3t')
        await self.um.upsert_user(test_user, domain_name="local")

        # get user
        user_metadata = await self.try_n_times_async(10,
                                                     1,
                                                     self.um.get_user,
                                                     test_user.username,
                                                     domain_name="local")

        # handle 7.0 roles w/ scopes/collections
        test_roles = user_roles
        if self.supports_collections():
            test_roles = []
            for r in user_roles:
                test_roles.append(
                    Role(name=r.name,
                         bucket=r.bucket,
                         scope='*',
                         collection='*'))

        self.assertIsNotNone(user_metadata)
        self.validate_user_and_metadata(user_metadata,
                                        user_roles=test_roles,
                                        groups=groups)

        # remove group
        remove_group = groups.pop()
        await self.um.drop_group(remove_group.name)
        await self.try_n_times_till_exception_async(
            10,
            1,
            self.um.get_group,
            remove_group.name,
            expected_exceptions=GroupNotFoundException)

        # get user to verify roles from removed group are removed
        user_metadata = await self.try_n_times_async(10,
                                                     1,
                                                     self.um.get_user,
                                                     test_user.username,
                                                     domain_name="local")

        # handle 7.0 roles w/ scopes/collections
        if self.supports_collections():
            test_roles = []
            for r in user_roles:
                test_roles.append(
                    Role(name=r.name,
                         bucket=r.bucket,
                         scope='*',
                         collection='*'))
        self.assertIsNotNone(user_metadata)
        self.validate_user_and_metadata(user_metadata,
                                        user_roles=test_roles,
                                        groups=groups)

        # cleanup
        await self.um.drop_user(test_user.username, domain_name="local")
        for group in groups:
            await self.um.drop_group(group.name)

    @async_test
    @skip_if_no_groups_async
    async def test_get_all_groups(self):
        roles = [
            Role(name='data_reader', bucket='*'),
            Role(name='data_writer', bucket='*')
        ]
        fresh_group = Group(name='my-test-group',
                            roles=roles,
                            description="test group description")
        await self.um.upsert_group(fresh_group)
        all_groups = await self.um.get_all_groups()
        # NOTE: we could well have other groups on this server, apart from the one we added, so
        # lets be ok with there being more of them.  However, the one we added
        # _MUST_ be there.
        known_group = Group('qweqwe', roles=[Role(name='admin')])
        await self.um.drop_group('my-test-group')
        for g in all_groups:
            if known_group == g:
                return
        self.fail("didn't find expected group in get_all_groups")

    @async_test
    @skip_if_no_groups_async
    async def test_timeout(self):
        await self.um.get_all_groups(timeout=timedelta(seconds=0.1))

    @async_test
    async def test_get_roles(self):
        roles = await self.um.get_roles()
        admin_desc = re.compile(
            r'.*all cluster features.*web console.*read and write all data.*$')
        for rad in reversed(roles):
            desc_matches = admin_desc.match(rad.description)
            if desc_matches:
                self.assertTrue(rad.role.name == 'admin'
                                and rad.display_name == 'Full Admin')
                return
        self.fail("No admin role found")

    # see PYCBC-1030
    @async_test
    async def test_get_roles_all_valid(self):
        roles = await self.um.get_roles()
        for r in roles:
            self.assertIsNotNone(r)

    @async_test
    @skip_if_no_groups_async
    async def test_missing_group(self):
        with self.assertRaises(GroupNotFoundException):
            await self.um.get_group('fred')

    @async_test
    async def test_missing_user(self):
        with self.assertRaises(UserNotFoundException):
            await self.um.get_user('keith')