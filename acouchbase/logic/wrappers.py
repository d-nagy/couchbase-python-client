from __future__ import annotations

from functools import partial, wraps

from couchbase.exceptions import (PYCBC_ERROR_MAP,
                                  CouchbaseException,
                                  DocumentExistsException,
                                  DocumentNotFoundException,
                                  ErrorMapperNew,
                                  ExceptionMap,
                                  MissingConnectionException)
from couchbase.logic import decode_value

# def build_exception(exc, exc_info=None, error_map=None, error_msg=None):
#     excptn = None
#     if exc is None and exc_info:
#         exc_cls = PYCBC_ERROR_MAP.get(exc_info.get('error_code', None), CouchbaseException)
#         new_exc_info = {k: v for k, v in exc_info if k in ['cinfo', 'inner_cause']}
#         excptn = exc_cls(message=exc_info.get('message', None), exc_info=new_exc_info)
#     else:
#         err_ctx = exc.error_context()
#         if err_ctx is not None:
#             excptn = ErrorMapper.parse_error_context(exc, mapping=error_map, excptn_msg=error_msg)
#         else:
#             exc_cls = PYCBC_ERROR_MAP.get(exc.err(), CouchbaseException)
#             excptn = exc_cls(message=exc.strerror())

#     if excptn is None:
#         exc_cls = PYCBC_ERROR_MAP.get(ExceptionMap.InternalSDKException.value, CouchbaseException)
#         excptn = exc_cls(message='Unknown error.')

#     return excptn


def call_async_fn(ft, self, fn, *args, **kwargs):
    try:
        fn(self, *args, **kwargs)
    except CouchbaseException as e:
        ft.set_exception(e)
    except Exception as e:
        if isinstance(e, (TypeError, ValueError)):
            ft.set_exception(e)
        else:
            print(f'base exception: {e}')
            exc_cls = PYCBC_ERROR_MAP.get(ExceptionMap.InternalSDKException.value, CouchbaseException)
            print(exc_cls.__name__)
            excptn = exc_cls(str(e))
            ft.set_exception(excptn)


class AsyncWrapper:

    @classmethod
    def inject_connection_callbacks(cls):

        def decorator(fn):
            @wraps(fn)
            def wrapped_fn(self, *args, **kwargs):
                ft = self.loop.create_future()

                def on_ok(res):
                    self._set_connection(res)
                    self.loop.call_soon_threadsafe(ft.set_result, True)

                def on_err(exc):
                    excptn = ErrorMapperNew.build_exception(exc)
                    self.loop.call_soon_threadsafe(ft.set_exception, excptn)

                kwargs["callback"] = on_ok
                kwargs["errback"] = on_err

                call_async_fn(ft, self, fn, *args, **kwargs)
                return ft

            return wrapped_fn

        return decorator

    @classmethod
    def inject_close_callbacks(cls):

        def decorator(fn):
            @wraps(fn)
            def wrapped_fn(self, *args, **kwargs):
                ft = self.loop.create_future()

                def on_ok(_):
                    self.loop.call_soon_threadsafe(ft.set_result, True)

                def on_err(exc):
                    excptn = ErrorMapperNew.build_exception(exc)
                    self.loop.call_soon_threadsafe(ft.set_exception, excptn)

                kwargs["callback"] = on_ok
                kwargs["errback"] = on_err

                call_async_fn(ft, self, fn, *args, **kwargs)
                return ft

            return wrapped_fn

        return decorator

    @classmethod
    def chain_connect_futures(cls, ft, self, fn, cft, **kwargs):
        """
        **INTERNAL**
        """
        if cft.cancelled():
            ft.cancel()
            return

        exc = cft.exception()
        if exc is not None:
            ft.set_exception(exc)
        else:
            self._connection = self._cluster.connection
            args = kwargs.pop("args", None)
            call_async_fn(ft, self, fn, *args, **kwargs)

    @classmethod
    def inject_bucket_open_callbacks(cls):

        def decorator(fn):
            @wraps(fn)
            def wrapped_fn(self, *args, **kwargs):
                ft = self.loop.create_future()

                def on_ok(_):
                    self._set_connected(True)
                    self.loop.call_soon_threadsafe(ft.set_result, True)

                def on_err(exc):
                    excptn = ErrorMapperNew.build_exception(exc)
                    self.loop.call_soon_threadsafe(ft.set_exception, excptn)

                kwargs["callback"] = on_ok
                kwargs["errback"] = on_err

                if not self._connection:
                    cluster_conn_ft = self._cluster.on_connect()
                    kwargs["args"] = args
                    cluster_conn_ft.add_done_callback(
                        partial(cls.chain_connect_futures, ft, self, fn, **kwargs))
                else:
                    call_async_fn(ft, self, fn, *args, **kwargs)

                return ft

            return wrapped_fn

        return decorator

    @classmethod
    def chain_futures(cls, ft, self, fn, cft, set_connection=False, **kwargs):
        """
        **INTERNAL**
        """
        if cft.cancelled():
            ft.cancel()
            return

        exc = cft.exception()
        if exc is not None:
            ft.set_exception(exc)
        else:
            if set_connection is True:
                # the bucket will set it's connection, need to make sure
                # the connection is set w/ the scope and collection as well
                self._scope._set_connection()
                self._set_connection()
            args = kwargs.pop("args", None)
            call_async_fn(ft, self, fn, *args, **kwargs)

    @classmethod   # noqa: C901
    def inject_cluster_callbacks(cls, return_cls, chain_connection=False, set_cluster_info=False):   # noqa: C901

        def decorator(fn):
            @wraps(fn)
            def wrapped_fn(self, *args, **kwargs):
                ft = self.loop.create_future()

                def on_ok(res):
                    if return_cls is None:
                        retval = None
                    elif return_cls is True:
                        retval = res
                    else:
                        retval = return_cls(res)

                    if set_cluster_info is True:
                        self._cluster_info = retval

                    self.loop.call_soon_threadsafe(ft.set_result, retval)

                def on_err(exc):
                    excptn = ErrorMapperNew.build_exception(exc)
                    self.loop.call_soon_threadsafe(ft.set_exception, excptn)

                kwargs["callback"] = on_ok
                kwargs["errback"] = on_err

                if not self._connection:
                    if chain_connection is True:
                        c_ft = self.on_connect()
                        # in order to keep arg passing simple, add operation args to kwargs
                        # this will keep the positional args passed to the callback only ones
                        # in the scope of handling logic w.r.t. to handling logic between the futures
                        # (the cluster connect future and the operation future)
                        kwargs["args"] = args
                        c_ft.add_done_callback(
                            partial(cls.chain_futures, ft, self, fn, **kwargs))
                    else:
                        exc = MissingConnectionException('Not connected.  Cannot perform operation.')
                        ft.set_exception(exc)
                else:
                    call_async_fn(ft, self, fn, *args, **kwargs)

                return ft

            return wrapped_fn

        return decorator

    @classmethod   # noqa: C901
    def inject_callbacks(cls, return_cls):   # noqa: C901

        def decorator(fn):
            @wraps(fn)
            def wrapped_fn(self, *args, **kwargs):
                ft = self.loop.create_future()

                def on_ok(res):
                    if return_cls is None:
                        retval = None
                    elif return_cls is True:
                        retval = res
                    else:
                        retval = return_cls(res)

                    self.loop.call_soon_threadsafe(ft.set_result, retval)

                def on_err(exc):
                    excptn = ErrorMapperNew.build_exception(exc)
                    self.loop.call_soon_threadsafe(ft.set_exception, excptn)

                kwargs["callback"] = on_ok
                kwargs["errback"] = on_err

                if not self._connection:
                    bucket_conn_ft = self._scope._connect_bucket()
                    # in order to keep arg passing simple, add operation args to kwargs
                    # This allows the _chain_futures callback to only worry about positional args
                    # outside the scope of the operation.
                    # Since, the kwargs passed to _chain_futures only apply to the operation, _chain_futures
                    # can easily determine what it needs to pass to the original wrapped fn
                    kwargs["args"] = args
                    bucket_conn_ft.add_done_callback(
                        partial(cls.chain_futures, ft, self, fn, set_connection=True, **kwargs))
                else:
                    call_async_fn(ft, self, fn, *args, **kwargs)

                return ft

            return wrapped_fn

        return decorator

    @classmethod   # noqa: C901
    def inject_callbacks_and_decode(cls, return_cls):   # noqa: C901

        def decorator(fn):
            @wraps(fn)
            def wrapped_fn(self, *args, **kwargs):
                ft = self.loop.create_future()
                transcoder = kwargs.pop('transcoder')

                def on_ok(res):
                    value = res.raw_result.get('value', None)
                    flags = res.raw_result.get('flags', None)

                    is_suboc = fn.__name__ == '_lookup_in_internal'
                    res.raw_result['value'] = decode_value(transcoder, value, flags, is_subdoc=is_suboc)

                    if return_cls is None:
                        retval = None
                    elif return_cls is True:
                        retval = res
                    else:
                        retval = return_cls(res)

                    self.loop.call_soon_threadsafe(ft.set_result, retval)

                def on_err(exc):
                    excptn = ErrorMapperNew.build_exception(exc)
                    self.loop.call_soon_threadsafe(ft.set_exception, excptn)

                kwargs["callback"] = on_ok
                kwargs["errback"] = on_err

                if not self._connection:
                    bucket_conn_ft = self._scope._connect_bucket()
                    # in order to keep arg passing simple, add operation args to kwargs
                    # This allows the _chain_futures callback to only worry about positional args
                    # outside the scope of the operation.
                    # Since, the kwargs passed to _chain_futures only apply to the operation, _chain_futures
                    # can easily determine what it needs to pass to the original wrapped fn
                    kwargs["args"] = args
                    bucket_conn_ft.add_done_callback(
                        partial(cls._chain_futures, ft, self, fn, set_connection=True, **kwargs))
                else:
                    call_async_fn(ft, self, fn, *args, **kwargs)

                return ft

            return wrapped_fn

        return decorator

    @classmethod
    def datastructure_op(cls, create_type=None):
        def decorator(fn):
            @wraps(fn)
            async def wrapped_fn(self, *args, **kwargs):
                try:
                    return await fn(self, *args, **kwargs)
                except DocumentNotFoundException:
                    if create_type is not None:
                        try:
                            await self._collection.insert(self._key, create_type())
                        except DocumentExistsException:
                            pass
                        return await fn(self, *args, **kwargs)
                    else:
                        raise

            return wrapped_fn
        return decorator
