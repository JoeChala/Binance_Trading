import hashlib
import hmac
import os
import time
from typing import Any
from urllib.parse import urlencode
import requests
from dotenv import load_dotenv

from bot.logging_config import get_logger
# loading api key
load_dotenv()

logger = get_logger("client")

BASE_URL = "https://testnet.binancefuture.com"

# typed exceptions for better error clarity
class BinanceAPIError(Exception):
    #raised when Binance returns an error payload
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"Binance API error {code}: {message}")

class BinanceAuthError(Exception):
    pass

class BinanceNetworkError(Exception):
    pass

class BinanceClient:
    """
    Responsibilities:
    - HMAC-SHA256 request signing
    - Attaching auth headers
    - HTTP request execution with retries
    - Translating API/network errors into typed exceptions
    - Logging every request and response
    """

    def __init__(self):
        self.api_key = os.getenv("BINANCE_API_KEY", "").strip()
        self.secret_key = os.getenv("BINANCE_SECRET_KEY", "").strip()

        if not self.api_key or not self.secret_key:
            raise BinanceAuthError("BINANCE_API_KEY and BINANCE_SECRET_KEY must be defined in your .env file")

        self.session = requests.Session()
        self.session.headers.update({
            "X-MBX-APIKEY": self.api_key,
            "Content-Type": "application/x-www-form-urlencoded",
        })

    def _timestamp(self) -> int:
        #Current time in milliseconds
        return int(time.time() * 1000)

    def _sign(self, params: dict[str, Any]) -> str:
        """
        Binance requires the signature to be computed over the URL-encoded 
        query string (including timestamp), then appended as a signature parameter
        """
        query_string: str = urlencode(params)
        signature: str = hmac.new(
            self.secret_key.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return signature

    def _signed_params(self, params: dict[str, Any]) -> dict[str, Any]:
        #attach timestamp and signature to a params object
        params["timestamp"] = self._timestamp()
        params["signature"] = self._sign(params)
        return params

    def _handle_response(self, response: requests.Response) -> dict[str, Any]:
        # check response JSON and raise typed exceptions on failure
        logger.debug(
            "Response | status=%s | body=%s",
            response.status_code,
            response.text[:500],  # truncate huge responses in logs
        )

        try:
            data = response.json()
        except ValueError:
            raise BinanceNetworkError(f"Non-JSON response (status {response.status_code}): {response.text}")

        # binance error payload always has a negative "code"
        if isinstance(data, dict) and "code" in data and data["code"] != 200:
            raise BinanceAPIError(code=data["code"], message=data.get("msg", "Unknown error"))

        response.raise_for_status()
        return data

    # Public API methods
    def post(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        """
        Sign and POST to a Binance endpoint.
        Used for all order placement calls.
        """
        signed = self._signed_params(params)
        url = f"{BASE_URL}{endpoint}"

        logger.info("POST %s | params=%s", endpoint, {
            k: v for k, v in params.items()
            if k not in ("signature", "timestamp")  # redact auth fields from INFO logs
        })
        logger.debug("Full signed params: %s", signed)

        try:
            response = self.session.post(url, data=signed, timeout=10)
        except requests.exceptions.Timeout:
            raise BinanceNetworkError(f"Request timed out: POST {endpoint}")
        except requests.exceptions.ConnectionError as e:
            raise BinanceNetworkError(f"Connection error: {e}")
        except requests.exceptions.RequestException as e:
            raise BinanceNetworkError(f"Unexpected network error: {e}")

        return self._handle_response(response)

    def get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Sign and GET from a Binance endpoint.
        Used for account/position queries.
        """
        signed = self._signed_params(params or {})
        url = f"{BASE_URL}{endpoint}"

        logger.info("GET %s", endpoint)
        logger.debug("Full signed params: %s", signed)

        try:
            response = self.session.get(url, params=signed, timeout=10)
        except requests.exceptions.Timeout:
            raise BinanceNetworkError(f"Request timed out: GET {endpoint}")
        except requests.exceptions.ConnectionError as e:
            raise BinanceNetworkError(f"Connection error: {e}")
        except requests.exceptions.RequestException as e:
            raise BinanceNetworkError(f"Unexpected network error: {e}")

        return self._handle_response(response)
    
    def get_exchange_info(self, symbol: str) -> dict[str, Any]:
        # Fetch trading rules for a specific symbol from Binance
        url = f"{BASE_URL}/fapi/v1/exchangeInfo"

        logger.info("Fetching exchange info for symbol: %s", symbol)

        try:
            response = self.session.get(url, timeout=10)
        except requests.exceptions.Timeout:
            raise BinanceNetworkError("Timed out fetching exchange info.")
        except requests.exceptions.ConnectionError as e:
            raise BinanceNetworkError(f"Connection error fetching exchange info: {e}")

        data = self._handle_response(response)

        # exchangeInfo returns ALL symbols
        for item in data.get("symbols", []):
            if item["symbol"] == symbol.upper():
                logger.debug("Exchange info found for %s", symbol)
                return item

        raise BinanceAPIError(code=-1121,message=f"Symbol '{symbol}' not found on Binance Futures testnet.",)