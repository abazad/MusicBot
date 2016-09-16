import logging
import os
import signal
import threading
from concurrent.futures import ThreadPoolExecutor

_shutdown = False
_executor = ThreadPoolExecutor()
_executed = []


def submit(fn):
    if _shutdown:
        raise ValueError("Tried to submit task after shutdown")
    return _executor.submit(fn)


def execute(fn, close_fn, name=None):
    """
    Executes a function in its own thread. The close_fn function will be called on shutdown to stop the thread.
    """
    if _shutdown:
        raise ValueError("Tried to execute task after shutdown")
    if fn:
        thread = threading.Thread(target=fn, name=name)
    else:
        thread = None
    _executed.append((thread, close_fn))
    if thread:
        thread.start()


def _shutdown_executed():
    for thread, close_fn in _executed:
        if (not thread) or thread.is_alive():
            try:
                close_fn()
            except (ValueError, AttributeError):
                logging.getLogger("musicbot").warning("Error executing close_fn for thread %s", str(thread))


def shutdown(wait=True):
    global _shutdown
    if not _shutdown:
        logging.getLogger("musicbot").info("Shutting down...")
        _shutdown = True
        _shutdown_executed()
        os.kill(os.getpid(), signal.SIGINT)
    return _executor.shutdown(wait)
