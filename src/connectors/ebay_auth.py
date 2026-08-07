"""Environment-only OAuth support for the official eBay Browse API."""

from __future__ import annotations

import base64
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import ConnectorError


ENVIRONMENTS = {
    "SANDBOX": "https://api.sandbox.ebay.com",
    "PRODUCTION": "https://api.ebay.com",
}
OAUTH_SCOPE = "https://api.ebay.com/oauth/api_scope"


@dataclass(frozen=True)
class EbayToken:
    value: str
    expires_at: float


class EbayAuth:
    def __init__(
        self, client_id: Optional[str] = None, client_secret: Optional[str] = None,
        environment: Optional[str] = None, opener: Callable = urlopen,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.client_id = client_id if client_id is not None else os.environ.get("PMI_EBAY_CLIENT_ID", "")
        self.client_secret = client_secret if client_secret is not None else os.environ.get("PMI_EBAY_CLIENT_SECRET", "")
        self.environment = (environment or os.environ.get("PMI_EBAY_ENVIRONMENT", "SANDBOX")).upper()
        if self.environment not in ENVIRONMENTS:
            raise ConnectorError("configuration", "PMI_EBAY_ENVIRONMENT must be SANDBOX or PRODUCTION.")
        self.opener = opener
        self.clock = clock
        self._token: Optional[EbayToken] = None
        self._lock = threading.Lock()

    @property
    def api_root(self) -> str:
        return ENVIRONMENTS[self.environment]

    def access_token(self) -> str:
        with self._lock:
            if self._token and self._token.expires_at - self.clock() > 60:
                return self._token.value
            self._token = self._request_token()
            return self._token.value

    def _request_token(self) -> EbayToken:
        if not self.client_id or not self.client_secret:
            raise ConnectorError(
                "authentication", "eBay credentials are not configured.",
                proposed_action="Set PMI_EBAY_CLIENT_ID and PMI_EBAY_CLIENT_SECRET in the environment.",
            )
        basic = base64.b64encode(
            (self.client_id + ":" + self.client_secret).encode("utf-8")
        ).decode("ascii")
        body = urlencode({"grant_type": "client_credentials", "scope": OAUTH_SCOPE}).encode("ascii")
        request = Request(
            self.api_root + "/identity/v1/oauth2/token", data=body, method="POST",
            headers={"Authorization": "Basic " + basic,
                     "Content-Type": "application/x-www-form-urlencoded",
                     "Accept": "application/json"},
        )
        try:
            with self.opener(request, timeout=15) as response:
                payload = json.loads(response.read(1024 * 1024).decode("utf-8"))
        except HTTPError as error:
            raise ConnectorError("authentication", "eBay authentication failed.", proposed_action="Verify the selected environment and eBay credentials.") from error
        except (URLError, TimeoutError) as error:
            raise ConnectorError("network", "eBay authentication service is unavailable.", transient=True) from error
        except (ValueError, KeyError, TypeError) as error:
            raise ConnectorError("malformed_data", "eBay authentication returned an invalid response.") from error
        token = payload.get("access_token")
        try:
            expires_in = int(payload.get("expires_in", 0))
        except (TypeError, ValueError):
            expires_in = 0
        if not isinstance(token, str) or not token or expires_in <= 0:
            raise ConnectorError("malformed_data", "eBay authentication returned an invalid response.")
        return EbayToken(token, self.clock() + expires_in)
