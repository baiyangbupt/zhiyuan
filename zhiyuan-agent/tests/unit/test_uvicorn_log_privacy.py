import io
import logging

import pytest
from uvicorn.logging import AccessFormatter

from app.util.uvicorn_log_privacy import (
    UvicornRequestQueryFilter,
    install_uvicorn_query_privacy,
)


def record(name, message, args):
    return logging.LogRecord(name, logging.INFO, __file__, 1, message, args, None)


@pytest.mark.parametrize("ending,args", [
    ("[accepted]", ("127.0.0.1:1234", "/ws/chat?ticket=SECRET&epoch=PRIVATE&since=9")),
    ("403", ("127.0.0.1:1234", "/ws/chat?ticket=SECRET")),
    ("%d", ("127.0.0.1:1234", "/ws/chat?ticket=SECRET", 401)),
])
def test_websocket_accept_and_reject_record_has_no_credentials(ending, args):
    # websockets, websockets-sansio and wsproto share these templates.
    entry = record("uvicorn.error", '%s - "WebSocket %s" ' + ending, args)
    entry.message = entry.getMessage()
    assert UvicornRequestQueryFilter().filter(entry)
    assert "/ws/chat?[redacted]" in entry.getMessage()
    assert "SECRET" not in repr(vars(entry))
    assert "PRIVATE" not in repr(vars(entry))


def test_http_access_keeps_uvicorn_formatter_argument_contract():
    entry = record("uvicorn.access", '%s - "%s %s HTTP/%s" %d',
                   ("127.0.0.1:1234", "GET", "/health?token=SECRET", "1.1", 200))
    UvicornRequestQueryFilter().filter(entry)
    formatted = AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s',
                                use_colors=False).format(entry)
    assert 'GET /health?[redacted] HTTP/1.1' in formatted
    assert '200' in formatted
    assert "SECRET" not in repr(vars(entry))


@pytest.mark.parametrize("message,args", [
    ('WebSocket /ws/chat?ticket=SECRET [accepted]', ()),
    ('WebSocket %(path)s %(status)s', {"path": "/ws/chat?ticket=SECRET", "status": 403}),
    ('GET https://example.test/ws/chat?%74icket=SECRET&token=OTHER', ()),
    ('WebSocket %s', ("/ws/chat?ticket=SECRET%2Fopaque%3Dvalue#fragment",)),
])
def test_other_uvicorn_message_and_argument_shapes(message, args):
    entry = record("uvicorn.error", message, args)
    UvicornRequestQueryFilter().filter(entry)
    assert "SECRET" not in repr(vars(entry))
    assert "OTHER" not in repr(vars(entry))
    assert "/ws/chat?[redacted]" in entry.getMessage()


def test_non_query_diagnostics_and_unrelated_loggers_are_unchanged():
    entry = record("uvicorn.error", "connection closed %s", (1000,))
    UvicornRequestQueryFilter().filter(entry)
    assert entry.getMessage() == "connection closed 1000"
    unrelated = record("app.other", "URL %s", ("/ws/chat?ticket=UNTOUCHED",))
    UvicornRequestQueryFilter().filter(unrelated)
    assert "UNTOUCHED" in unrelated.getMessage()


@pytest.mark.parametrize("path", [
    '/ws/chat?ticket="SECRET"&token=OTHER',
    '/ws/chat?ticket=SECRET OTHER\nopaque',
])
def test_complete_target_argument_redacts_even_malformed_query(path):
    entry = record("uvicorn.error", 'WebSocket %s [accepted]', (path,))
    UvicornRequestQueryFilter().filter(entry)
    assert entry.getMessage() == 'WebSocket /ws/chat?[redacted] [accepted]'
    assert "SECRET" not in repr(vars(entry))


def test_install_is_idempotent_and_filters_before_multiple_handlers():
    names = ("uvicorn.error", "uvicorn.access")
    original = {name: list(logging.getLogger(name).filters) for name in names}
    logger = logging.getLogger("uvicorn.error")
    old_level, old_propagate, old_handlers = logger.level, logger.propagate, logger.handlers[:]
    streams = [io.StringIO(), io.StringIO()]
    seen = []

    class RecordHandler(logging.Handler):
        def emit(self, entry):
            seen.append(repr(vars(entry)))

    try:
        for name in names:
            logging.getLogger(name).filters = []
        install_uvicorn_query_privacy()
        install_uvicorn_query_privacy()
        assert all(len(logging.getLogger(name).filters) == 1 for name in names)
        logger.handlers = [logging.StreamHandler(stream) for stream in streams] + [RecordHandler()]
        logger.propagate = False
        logger.setLevel(logging.INFO)
        logger.info('%s - "WebSocket %s" [accepted]', "127.0.0.1", "/ws/chat?ticket=SECRET")
        assert all("/ws/chat?[redacted]" in stream.getvalue() for stream in streams)
        assert all("SECRET" not in value for value in seen)
    finally:
        logger.handlers = old_handlers
        logger.setLevel(old_level)
        logger.propagate = old_propagate
        for name, filters in original.items():
            logging.getLogger(name).filters = filters
