import tempfile
import os

from couchbase.exceptions import (AuthError, ArgumentError,
                                  BucketNotFoundError, ConnectError,
                                  NotFoundError)
from couchbase.libcouchbase import Connection

from tests.base import CouchbaseTestCase


class ConnectionTest(CouchbaseTestCase):
    def test_connection_host_port(self):
        cb = Connection(self.host, self.port, self.username, self.password,
                        self.bucket_prefix)
        # Connection didn't throw an error
        self.assertIsInstance(cb, Connection)

    def test_server_not_found(self):
        self.assertRaises(ConnectError, Connection, 'example.com', self.port,
                          self.username, self.password, self.bucket_prefix)
        self.assertRaises(ConnectError, Connection, self.host, 34567,
                          self.username, self.password, self.bucket_prefix)

    def test_bucket(self):
        cb = Connection(username=self.username, password=self.password,
                        bucket=self.bucket_prefix)
        self.assertIsInstance(cb, Connection)

        cb = Connection(self.host, self.port, self.username, self.password,
                        self.bucket_prefix)
        self.assertIsInstance(cb, Connection)

        cb = Connection(self.host, self.port,
                        bucket=self.bucket_prefix + '_sasl',
                        password=self.bucket_password)
        self.assertIsInstance(cb, Connection)

    def test_bucket_not_found(self):
        self.assertRaises(BucketNotFoundError, Connection, self.host,
                          self.port, self.username, self.password,
                          'this_bucket_does_not_exist')

    def test_bucket_wrong_credentials(self):
        self.assertRaises(AuthError, Connection, self.host, self.port,
                          bucket=self.bucket_prefix,
                          username='wrong_username',
                          password='wrong_password')
        self.assertRaises(AuthError, Connection, self.host, self.port,
                          bucket=self.bucket_prefix, password='wrong_password')

        self.assertRaises(AuthError, Connection, self.host, self.port,
                          password='wrong_password',
                          bucket=self.bucket_prefix + '_sasl')

    def test_quiet(self):
        cb = Connection(username=self.username, password=self.password,
                        bucket=self.bucket_prefix)
        self.assertRaises(NotFoundError, cb.get, 'missing_key')

        cb = Connection(username=self.username, password=self.password,
                        bucket=self.bucket_prefix, quiet=True)
        val1 = cb.get('missing_key')
        self.assertIsNone(val1)

        cb = Connection(username=self.username, password=self.password,
                        bucket=self.bucket_prefix, quiet=False)
        self.assertRaises(NotFoundError, cb.get, 'missing_key')


    def test_conncache(self):
        cachefile = tempfile.NamedTemporaryFile()
        cb = Connection(username=self.username, password=self.password,
                        bucket=self.bucket_prefix, conncache=cachefile.name)
        self.assertTrue(cb.set("foo", "bar"))

        cb2 = Connection(username=self.username, password=self.password,
                         bucket=self.bucket_prefix, conncache=cachefile.name)
        self.assertTrue(cb2.set("foo", "bar"))
        self.assertEquals("bar", cb.get("foo"))

        sb = os.stat(cachefile.name)
        self.assertTrue(sb.st_size > 0)

        print("Filename is", cachefile.name)

        # TODO, see what happens when bad path is used
        # apparently libcouchbase does not report this failure.

    def test_connection_errors(self):
        cb = Connection(username='bad',
                        password='bad',
                        bucket='meh',
                        host='localhost', port=1,
                        _no_connect_exceptions=True)
        errors = cb.errors()
        self.assertTrue(len(errors))
        self.assertEqual(len(errors[0]), 2)

        cb = Connection(username=self.username, password=self.password,
                        bucket=self.bucket_prefix)
        self.assertFalse(len(cb.errors()))

    def test_multi_hosts(self):
        kwargs = {
            'username' : self.username,
            'password' : self.password,
            'bucket' : self.bucket_prefix
        }

        cb = Connection(host=['localhost'], **kwargs)
        self.assertTrue(cb.set("foo", "bar"))

        cb = Connection(host=[('localhost', 8091)], **kwargs)
        self.assertTrue(cb.set("foo", "bar"))

        cb = Connection(host=[('localhost', 1), ('localhost', 8091)], **kwargs)
        self.assertTrue(cb.set("foo", "bar"))

if __name__ == '__main__':
    unittest.main()
