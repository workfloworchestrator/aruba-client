# Copyright 2019-2025 SURF.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Shared httpx plumbing for the raw HPE GreenLake and UXI calls.

The Aruba Central data calls go through pycentral, whose ``NewCentralBase.command()``
already retries transient failures (incl. 429). The GreenLake OAuth/workspace calls in
:mod:`aruba_client.client` and the whole UXI API in :mod:`aruba_client.uxi` use plain
httpx instead, so this module provides the matching retry/backoff and the base error.
"""

import time
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

_DEFAULT_TOKEN_TTL: int = 7200
_TOKEN_EXPIRY_BUFFER: int = 300

# Values match pycentral.base.RETRY_* defaults so both transports back off alike.
_RETRY_MAX_ATTEMPTS: int = 3
_RETRY_INITIAL_BACKOFF: float = 1.0
_RETRY_BACKOFF_MULTIPLIER: float = 2.0
_RETRY_MAX_BACKOFF: float = 10.0
_RETRY_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


class ArubaClientError(Exception):
    pass


def _request_with_retry(method: str, url: str, *, context: str, **kwargs: Any) -> httpx.Response:
    """Issue an httpx request with retry on transient failures.

    Retries on transport errors (connection/timeout) and retryable status codes
    (429 + 5xx) with exponential backoff, then returns the final response so the
    caller can apply its own status-specific error handling. Non-retryable
    responses (e.g. 401/400) are returned immediately on the first attempt.
    """
    backoff = _RETRY_INITIAL_BACKOFF
    for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
        is_last = attempt == _RETRY_MAX_ATTEMPTS
        try:
            with httpx.Client(http2=True) as client:
                response = client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            if is_last:
                raise ArubaClientError(f"{context} failed after {attempt} attempts: {exc}") from exc
            logger.warning(
                "Retrying after transport error",
                context=context,
                attempt=attempt,
                error=str(exc),
                backoff=backoff,
            )
        else:
            if is_last or response.status_code not in _RETRY_STATUS_CODES:
                return response
            logger.warning(
                "Retrying after retryable status",
                context=context,
                attempt=attempt,
                status_code=response.status_code,
                backoff=backoff,
            )
        time.sleep(backoff)
        backoff = min(backoff * _RETRY_BACKOFF_MULTIPLIER, _RETRY_MAX_BACKOFF)

    # Unreachable: the final attempt always returns or raises above.
    raise ArubaClientError(f"{context}: retries exhausted")
