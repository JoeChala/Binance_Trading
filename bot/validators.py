from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Any

from bot.logging_config import get_logger
from bot.client import BinanceClient

logger = get_logger("validators")

VALID_SIDES = {"BUY", "SELL"}
VALID_ORDER_TYPES = {"MARKET", "LIMIT", "STOP_MARKET"}

constraints_cache: dict[str, dict[str, Decimal]] = {}


def get_symbol_constraints(symbol: str,client: BinanceClient) -> dict[str, Decimal]:
    # Fetch and parse LOT_SIZE, PRICE_FILTER, and MIN_NOTIONAL filters for a symbol from Binance exchange info.
    
    sym = symbol.upper()

    if sym in constraints_cache:
        logger.debug("Using cached constraints for %s", sym)
        return constraints_cache[sym]

    logger.info("Fetching live constraints for %s from Binance", sym)
    info = client.get_exchange_info(sym)

    constraints: dict[str, Decimal] = {}

    for f in info.get("filters", []):
        ftype = f.get("filterType")

        if ftype == "LOT_SIZE":
            constraints["step_size"] = Decimal(f["stepSize"])
            constraints["min_qty"]   = Decimal(f["minQty"])
            constraints["max_qty"]   = Decimal(f["maxQty"])

        elif ftype == "PRICE_FILTER":
            constraints["tick_size"] = Decimal(f["tickSize"])
            constraints["min_price"] = Decimal(f["minPrice"])
            constraints["max_price"] = Decimal(f["maxPrice"])

        elif ftype == "MIN_NOTIONAL":
            # Futures uses "notional" key, Spot uses "minNotional"
            raw = f.get("notional") or f.get("minNotional", "5")
            constraints["min_notional"] = Decimal(raw)

    # Safety fallbacks if any filter was missing
    constraints.setdefault("step_size",    Decimal("0.001"))
    constraints.setdefault("min_qty",      Decimal("0.001"))
    constraints.setdefault("max_qty",      Decimal("100000"))
    constraints.setdefault("tick_size",    Decimal("0.01"))
    constraints.setdefault("min_price",    Decimal("0.01"))
    constraints.setdefault("max_price",    Decimal("10000000"))
    constraints.setdefault("min_notional", Decimal("5"))

    logger.debug("Constraints for %s: %s", sym, constraints)
    constraints_cache[sym] = constraints
    return constraints

def clear_constraints_cache() -> None:
    constraints_cache.clear()

def validate_symbol(symbol: str) -> tuple[str, str | None]:
    cleaned = symbol.upper().replace("-", "").replace("_", "").strip()

    if len(cleaned) < 5:
        return cleaned, f"Symbol '{symbol}' is too short. Expected format: BTCUSDT"

    if not cleaned.isalpha():
        return cleaned, f"Symbol '{symbol}' contains invalid characters."

    return cleaned, None


def validate_side(side: str) -> tuple[str, str | None]:
    cleaned = side.upper().strip()
    if cleaned not in VALID_SIDES:
        return cleaned, (f"Invalid side '{side}'. Must be one of: {', '.join(sorted(VALID_SIDES))}")
    return cleaned, None


def validate_order_type(order_type: str) -> tuple[str, str | None]:
    cleaned = order_type.upper().strip()
    if cleaned not in VALID_ORDER_TYPES:
        return cleaned, (f"Invalid order type '{order_type}'. Must be one of: {', '.join(sorted(VALID_ORDER_TYPES))}")
    return cleaned, None


def validate_quantity(quantity: str,symbol: str,client: BinanceClient,price = None):
    #Validate quantity against live Binance exchange constraints.
    try:
        qty = Decimal(str(quantity))
    except InvalidOperation:
        return str(quantity), f"Quantity '{quantity}' is not a valid number."

    if qty <= 0:
        return str(qty), "Quantity must be greater than zero."

    c = get_symbol_constraints(symbol, client)

    if qty < c["min_qty"]:
        return str(qty), (f"Quantity {qty} is below the minimum of {c['min_qty']} for {symbol}.")

    if qty > c["max_qty"]:
        return str(qty), (f"Quantity {qty} exceeds the maximum of {c['max_qty']} for {symbol}.")

    if (qty % c["step_size"]) != Decimal("0"):
        example_1 = c["min_qty"]
        example_2 = c["min_qty"] * 2
        example_3 = c["min_qty"] * 10
        return str(qty), (f"Quantity {qty} is not a valid step for {symbol}. Must be a multiple of {c['step_size']}")

    if price is not None:
        try:
            notional = qty * Decimal(str(price))
            if notional < c["min_notional"]:
                return str(qty), (f"Order notional value ${notional:.2f} USDT is below the minimum of ${c['min_notional']} USDT for {symbol}.")
        except InvalidOperation:
            pass  # price validated separately

    logger.debug("Quantity validated: %s", qty)
    return str(qty), None


def validate_price(price: str,symbol: str,client: BinanceClient):
    # Validate price against live tick_size and price bounds.
    
    try:
        p = Decimal(str(price))
    except InvalidOperation:
        return str(price), f"Price '{price}' is not a valid number."

    if p <= 0:
        return str(price), "Price must be greater than zero."

    c = get_symbol_constraints(symbol, client)

    if p < c["min_price"]:
        return str(p), (f"Price {p} is below the minimum allowed price of {c['min_price']}.")

    if p > c["max_price"]:
        return str(p), (f"Price {p} exceeds the maximum allowed price of {c['max_price']}.")

    if (p % c["tick_size"]) != Decimal("0"):
        return str(p), (f"Price {p} is not a valid tick for {symbol}. Must be a multiple of {c['tick_size']}.")

    logger.debug("Price validated: %s", p)
    return str(p), None


def validate_stop_price(stop_price: str, price: str | None, side: str, symbol: str, client: BinanceClient):
    # Validate stop price for STOP_MARKET orders.

    cleaned, err = validate_price(stop_price, symbol, client)
    if err:
        return cleaned, err

    if not price:
        logger.debug("No reference price provided — skipping stop price direction check")
        return cleaned, None

    try:
        sp = Decimal(cleaned)
        lp = Decimal(str(price))
    except InvalidOperation:
        return cleaned, "Could not compare stop price and reference price."

    if side.upper() == "BUY" and sp <= lp:
        return cleaned, (f"For a BUY STOP_MARKET, stop price ({sp}) must be above the reference price ({lp}).")

    if side.upper() == "SELL" and sp >= lp:
        return cleaned, (f"For a SELL STOP_MARKET, stop price ({sp}) must be below the reference price ({lp}).")

    logger.debug("Stop price validated: %s", cleaned)
    return cleaned, None


def validate_order(order: dict[str, Any],client: BinanceClient) -> list[str]:
    #Validate a complete order dict against live Binance constraints.
    errors: list[str] = []

    symbol     = order.get("symbol", "")
    side       = order.get("side", "")
    order_type = order.get("order_type", "")
    quantity   = order.get("quantity", "")
    price      = order.get("price")
    stop_price = order.get("stop_price")

    sym_cleaned, err = validate_symbol(symbol)
    if err:
        errors.append(err)
        # Can't validate further without a valid symbol
        return errors

    _, err = validate_side(side)
    if err:
        errors.append(err)

    _, err = validate_order_type(order_type)
    if err:
        errors.append(err)

    # Quantity — fetch live constraints here
    try:
        _, err = validate_quantity(quantity, sym_cleaned, client, price)
        if err:
            errors.append(err)
    except Exception as e:
        errors.append(f"Could not validate quantity: {e}")

    # LIMIT — price required
    if order_type.upper() == "LIMIT":
        if not price:
            errors.append("Price is required for LIMIT orders.")
        else:
            try:
                _, err = validate_price(price, sym_cleaned, client)
                if err:
                    errors.append(err)
            except Exception as e:
                errors.append(f"Could not validate price: {e}")

    # STOP_MARKET — stop_price required
    if order_type.upper() == "STOP_MARKET":
        if not stop_price:
            errors.append("stop_price is required for STOP_MARKET orders.")
        else:
            try:
                ref = price if price and Decimal(str(price)) > 0 else None
                _, err = validate_stop_price(stop_price, ref, side, sym_cleaned, client)
                if err:
                    errors.append(err)
            except Exception as e:
                errors.append(f"Could not validate stop price: {e}")

    if errors:
        logger.warning("Order validation failed: %s", errors)
    else:
        logger.debug("Order validation passed: %s %s %s qty=%s",side, order_type, symbol, quantity,)

    return errors