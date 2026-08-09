import logging
from contextvars import ContextVar, Token
from typing import Callable, Optional

logger = logging.getLogger(__name__)

EventSink = Callable[[dict], None]

_sink_var: ContextVar[Optional[EventSink]] = ContextVar("coding_agent_event_sink", default=None)


def set_event_sink(sink: EventSink) -> Token:
    return _sink_var.set(sink)


def reset_event_sink(token: Token) -> None:
    _sink_var.reset(token)


def sink_active() -> bool:
    return _sink_var.get() is not None


def emit(event: dict) -> None:
    sink = _sink_var.get()
    if sink is None:
        return
    try:
        sink(event)
    except Exception:
        logger.exception("Event sink failed")
