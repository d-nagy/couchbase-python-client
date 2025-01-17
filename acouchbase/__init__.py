import asyncio
import selectors


class LoopValidator:
    REQUIRED_METHODS = {'add_reader', 'remove_reader',
                        'add_writer', 'remove_writer'}

    @staticmethod
    def _get_working_loop():
        evloop = asyncio.get_event_loop()
        gen_new_loop = not LoopValidator._is_valid_loop(evloop)
        if gen_new_loop:
            evloop.close()
            selector = selectors.SelectSelector()
            new_loop = asyncio.SelectorEventLoop(selector)
            asyncio.set_event_loop(new_loop)
            return new_loop

        return evloop

    @staticmethod
    def _is_valid_loop(evloop):
        if not evloop:
            return False
        for meth in LoopValidator.REQUIRED_METHODS:
            abs_meth, actual_meth = (
                getattr(asyncio.AbstractEventLoop, meth), getattr(evloop.__class__, meth))
            if abs_meth == actual_meth:
                return False
        return True

    @staticmethod
    def get_event_loop(evloop):
        if LoopValidator._is_valid_loop(evloop):
            return evloop
        return LoopValidator._get_working_loop()

    @staticmethod
    def close_loop():
        evloop = asyncio.get_event_loop()
        evloop.close()


def get_event_loop(
    evloop=None,  # type: asyncio.AbstractEventLoop
):
    """
    Get an event loop compatible with acouchbase.
    Some Event loops, such as ProactorEventLoop (the default asyncio event
    loop for Python 3.8 on Windows) are not compatible with acouchbase as
    they don't implement all members in the abstract base class.

    :param evloop: preferred event loop
    :return: The preferred event loop, if compatible, otherwise, a compatible
    alternative event loop.
    """
    return LoopValidator.get_event_loop(evloop)
