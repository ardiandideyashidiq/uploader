from __future__ import annotations

import time
from typing import Callable, TypeVar

import requests

T = TypeVar("T")

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (1, 2)


def is_retryable_upload_error(error: Exception) -> bool:
    return isinstance(error, (requests.RequestException, RuntimeError))


def retry_upload(
    fn: Callable[[], T],
    *,
    retryable: Callable[[Exception], bool] = is_retryable_upload_error,
) -> T:
    last_error: Exception | None = None

    for attempt in range(MAX_ATTEMPTS):
        try:
            return fn()
        except Exception as error:
            last_error = error
            if not retryable(error) or attempt == MAX_ATTEMPTS - 1:
                raise
            time.sleep(BACKOFF_SECONDS[attempt])

    raise last_error or RuntimeError("retry_upload failed")
