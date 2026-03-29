from decimal import Decimal
from typing import Any

from bot.client import BinanceClient, BinanceAPIError, BinanceNetworkError
from bot.logging_config import get_logger
from bot.validators import validate_order

logger = get_logger("orders")

ORDER_ENDPOINT = "/fapi/v1/order"


# ------------------------------------------------------------------
# Response normaliser
# ------------------------------------------------------------------

def _parse_response(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Normalise a Binance order response into a clean dict
    with only the fields we care about.

    Raw Binance fields we map:
        orderId       → order_id
        status        → status         (NEW, FILLED, PARTIALLY_FILLED, CANCELED)
        executedQty   → executed_qty
        avgPrice      → avg_price      (0 if not yet filled)
        origQty       → orig_qty
        price         → price          (limit price; "0" for market)
        side          → side
        type          → order_type
        symbol        → symbol
        updateTime    → updated_at
    """
    avg_price = raw.get("avgPrice", "0")

    return {
        "order_id":    raw.get("orderId"),
        "symbol":      raw.get("symbol"),
        "side":        raw.get("side"),
        "order_type":  raw.get("type"),
        "status":      raw.get("status"),
        "orig_qty":    raw.get("origQty"),
        "executed_qty": raw.get("executedQty", "0"),
        "avg_price":   avg_price if avg_price != "0" else "not filled yet",
        "price":       raw.get("price", "0"),
        "updated_at":  raw.get("updateTime"),
    }


# ------------------------------------------------------------------
# Order builders
# Each returns the raw params dict to POST to Binance.
# Kept separate so they are testable in isolation.
# ------------------------------------------------------------------

def _build_market_order(
    symbol: str,
    side: str,
    quantity: str,
) -> dict[str, Any]:
    return {
        "symbol":   symbol,
        "side":     side,
        "type":     "MARKET",
        "quantity": quantity,
    }


def _build_limit_order(
    symbol: str,
    side: str,
    quantity: str,
    price: str,
    time_in_force: str = "GTC",
) -> dict[str, Any]:
    return {
        "symbol":      symbol,
        "side":        side,
        "type":        "LIMIT",
        "quantity":    quantity,
        "price":       price,
        "timeInForce": time_in_force,
    }


def _build_stop_market_order(
    symbol: str,
    side: str,
    quantity: str,
    stop_price: str,
) -> dict[str, Any]:
    """
    STOP_MARKET: triggers a market order when price hits stop_price.

    Use case:
    - SELL stop: protect a long position (stop-loss)
    - BUY  stop: enter on breakout above a level
    """
    return {
        "symbol":    symbol,
        "side":      side,
        "type":      "STOP_MARKET",
        "quantity":  quantity,
        "stopPrice": stop_price,
    }


# ------------------------------------------------------------------
# Public order placement functions
# ------------------------------------------------------------------

def place_order(
    client: BinanceClient,
    symbol: str,
    side: str,
    order_type: str,
    quantity: str,
    price: str | None = None,
    stop_price: str | None = None,
    time_in_force: str = "GTC",
) -> dict[str, Any]:
    """
    Validate, build, and place an order.

    This is the single entry point for all order types.
    The CLI calls this — it never touches the client directly.

    Returns a normalised order result dict.
    Raises ValueError on validation failure.
    Raises BinanceAPIError on API rejection.
    Raises BinanceNetworkError on connectivity issues.
    """

    # ---- 1. Validate ------------------------------------------------
    order_input = {
        "symbol":     symbol.upper(),
        "side":       side.upper(),
        "order_type": order_type.upper(),
        "quantity":   quantity,
        "price":      price,
        "stop_price": stop_price,
    }

    errors = validate_order(order_input)
    if errors:
        # Join all errors into one readable message
        raise ValueError("Validation failed:\n" + "\n".join(f"  • {e}" for e in errors))

    sym  = symbol.upper()
    sd   = side.upper()
    otype = order_type.upper()

    # ---- 2. Build params --------------------------------------------
    if otype == "MARKET":
        params = _build_market_order(sym, sd, quantity)

    elif otype == "LIMIT":
        if not price:
            raise ValueError("Price is required for LIMIT orders.")
        params = _build_limit_order(sym, sd, quantity, price, time_in_force)

    elif otype == "STOP_MARKET":
        if not stop_price:
            raise ValueError("stop_price is required for STOP_MARKET orders.")
        params = _build_stop_market_order(sym, sd, quantity, stop_price)

    else:
        raise ValueError(f"Unsupported order type: {order_type}")

    # ---- 3. Log the request summary ---------------------------------
    logger.info(
        "Placing order | %s %s %s | qty=%s | price=%s | stop=%s",
        sd, otype, sym, quantity, price or "N/A", stop_price or "N/A",
    )

    # ---- 4. Send to Binance -----------------------------------------
    try:
        raw_response = client.post(ORDER_ENDPOINT, params)
    except BinanceAPIError as e:
        logger.error("API rejected order: code=%s msg=%s", e.code, e.message)
        raise
    except BinanceNetworkError as e:
        logger.error("Network failure during order placement: %s", e)
        raise

    # ---- 5. Normalise and return ------------------------------------
    result = _parse_response(raw_response)

    logger.info(
        "Order placed | id=%s | status=%s | executed=%s @ %s",
        result["order_id"],
        result["status"],
        result["executed_qty"],
        result["avg_price"],
    )

    return result


# ------------------------------------------------------------------
# Convenience wrappers — used directly by the CLI for clarity
# ------------------------------------------------------------------

def place_market_order(
    client: BinanceClient,
    symbol: str,
    side: str,
    quantity: str,
) -> dict[str, Any]:
    return place_order(
        client=client,
        symbol=symbol,
        side=side,
        order_type="MARKET",
        quantity=quantity,
    )


def place_limit_order(
    client: BinanceClient,
    symbol: str,
    side: str,
    quantity: str,
    price: str,
    time_in_force: str = "GTC",
) -> dict[str, Any]:
    return place_order(
        client=client,
        symbol=symbol,
        side=side,
        order_type="LIMIT",
        quantity=quantity,
        price=price,
        time_in_force=time_in_force,
    )


def place_stop_market_order(
    client: BinanceClient,
    symbol: str,
    side: str,
    quantity: str,
    stop_price: str,
) -> dict[str, Any]:
    return place_order(
        client=client,
        symbol=symbol,
        side=side,
        order_type="STOP_MARKET",
        quantity=quantity,
        stop_price=stop_price,
    )