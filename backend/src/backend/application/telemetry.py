"""Dependency-free operation tracing. Arguments, results and exception text stay private."""

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from time import perf_counter
from uuid import uuid4

TRACE = 5
trace_id: ContextVar[str | None] = ContextVar("backend_trace_id", default=None)
span_id: ContextVar[str | None] = ContextVar("backend_span_id", default=None)


def event(logger, name, *, level=TRACE, **fields):
    """Emit explicitly selected operational fields; callers must never pass payloads."""
    if logger.isEnabledFor(level):
        logger.log(level, name, extra={"event_fields": fields})


@contextmanager
def operation(logger, name, *, level=TRACE):
    """Correlate nested operations, including exceptions and cancellation, and time them."""
    if not logger.isEnabledFor(level):
        yield
        return
    root = trace_id.set(uuid4().hex) if trace_id.get() is None else None
    parent = span_id.get()
    current = span_id.set(uuid4().hex[:16])
    started = perf_counter()
    event(logger, name + ".started", level=level, parent_span_id=parent)
    try:
        yield
    except BaseException as error:
        successful_exit = isinstance(error, SystemExit) and error.code in (None, 0)
        event(
            logger,
            name + (".completed" if successful_exit else ".failed"),
            level=level,
            **({} if successful_exit else {"error_type": type(error).__name__}),
            duration_ms=round((perf_counter() - started) * 1000, 3),
        )
        raise
    else:
        event(
            logger,
            name + ".completed",
            level=level,
            duration_ms=round((perf_counter() - started) * 1000, 3),
        )
    finally:
        span_id.reset(current)
        if root is not None:
            trace_id.reset(root)


def traced(function):
    """Trace a synchronous operation without evaluating arguments or return values."""
    logger = function_logger(function)

    @wraps(function)
    def wrapped(*args, **kwargs):
        if not logger.isEnabledFor(TRACE):
            return function(*args, **kwargs)
        with operation(logger, function.__qualname__):
            return function(*args, **kwargs)

    return wrapped


def function_logger(function):
    spec = function.__globals__.get("__spec__")
    return logging.getLogger(
        spec.name if function.__module__ == "__main__" and spec else function.__module__
    )
