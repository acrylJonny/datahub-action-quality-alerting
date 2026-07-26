"""In-process retry with exponential backoff for transient sink failures.

`requests` is not imported here (it is a runtime-only dep); transient errors are
classified by response status code and exception class name instead.
"""

import logging
import time
from collections.abc import Callable
from typing import TypeVar

from action_quality_alerting.config import RetryConfig

logger = logging.getLogger(__name__)

T = TypeVar("T")

_TRANSIENT_EXC_NAMES = {
    "Timeout",
    "ConnectTimeout",
    "ReadTimeout",
    "ConnectionError",
    "ChunkedEncodingError",
}


def is_transient(exc: Exception) -> bool:
    """Retry on 429 / 5xx and on network-level errors; everything else (4xx, bad
    template, auth) is permanent and fails fast."""
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status is not None:
        return status == 429 or status >= 500
    return type(exc).__name__ in _TRANSIENT_EXC_NAMES


def retry_call(
    fn: Callable[[], T],
    *,
    retry: RetryConfig,
    is_retryable: Callable[[Exception], bool] = is_transient,
    sleep: Callable[[float], None] = time.sleep,
    label: str = "",
) -> T:
    attempt = 0
    delay = retry.backoff_seconds
    last: Exception | None = None
    while True:
        attempt += 1
        try:
            return fn()
        except Exception as exc:
            last = exc
            if attempt >= retry.max_attempts or not is_retryable(exc):
                raise
            wait = min(delay, retry.max_backoff_seconds)
            logger.warning(
                f"[retry{':' + label if label else ''}] attempt {attempt}/{retry.max_attempts} "
                f"failed ({exc}); retrying in {wait:.1f}s"
            )
            sleep(wait)
            delay *= retry.backoff_multiplier
    # Unreachable, but keeps type-checkers happy about `last`.
    raise last  # type: ignore[misc]
