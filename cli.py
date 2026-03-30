import sys
from typing import Optional
import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich import box

from bot.client import BinanceClient, BinanceAPIError, BinanceNetworkError, BinanceAuthError
from bot.orders import place_market_order, place_limit_order, place_stop_market_order
from bot.validators import validate_order, get_symbol_constraints
from bot.logging_config import get_logger


app = typer.Typer(name="trading-bot",help="Binance Futures Testnet trading bot",add_completion=False,pretty_exceptions_enable=False)

console = Console()
logger  = get_logger("cli")


def _make_client() -> BinanceClient:
    try:
        return BinanceClient()
    except BinanceAuthError as e:
        console.print(f"\n[bold red]Auth error:[/bold red] {e}")
        console.print("Add your keys to the [cyan].env[/cyan] file and try again.")
        raise typer.Exit(code=1)


def print_request_summary(
    symbol: str,
    side: str,
    order_type: str,
    quantity: str,
    price: str | None = None,
    stop_price: str | None = None,
) -> None:
    """Print a formatted table of what we're about to send."""
    table = Table(
        title="Order request",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Field",  style="dim", width=16)
    table.add_column("Value",  style="bold white")

    side_colour = "green" if side.upper() == "BUY" else "red"

    table.add_row("Symbol",     symbol.upper())
    table.add_row("Side",       f"[{side_colour}]{side.upper()}[/{side_colour}]")
    table.add_row("Order type", order_type.upper())
    table.add_row("Quantity",   quantity)

    if price:
        table.add_row("Price",  price)
    if stop_price:
        table.add_row("Stop price", stop_price)

    console.print()
    console.print(table)


def print_order_result(result: dict) -> None:
    # Print a formatted table of the exchange response
    status = result.get("status", "UNKNOWN")
    status_colour = "green" if status == "FILLED" else "yellow"

    table = Table(
        title="Order response",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Field",  style="dim", width=16)
    table.add_column("Value",  style="bold white")

    table.add_row("Order ID",     str(result.get("order_id")))
    table.add_row("Symbol",       str(result.get("symbol")))
    table.add_row("Side",         str(result.get("side")))
    table.add_row("Type",         str(result.get("order_type")))
    table.add_row("Status",       f"[{status_colour}]{status}[/{status_colour}]")
    table.add_row("Quantity",     str(result.get("orig_qty")))
    table.add_row("Executed qty", str(result.get("executed_qty")))
    table.add_row("Avg price",    str(result.get("avg_price")))

    console.print()
    console.print(table)

    if status == "FILLED":
        console.print(Panel(
            "[bold green]Order filled successfully.[/bold green]",
            border_style="green",
        ))
    else:
        console.print(Panel(
            f"[bold yellow]Order placed. Status: {status}[/bold yellow]\n"
            "Limit/stop orders sit in the book until price is reached.",
            border_style="yellow",
        ))


def print_validation_errors(errors: list[str]) -> None:
    error_text = "\n".join(f"  [red]•[/red] {e}" for e in errors)
    console.print(Panel(f"[bold red]Validation failed[/bold red]\n\n{error_text}",border_style="red"))


def print_constraints(symbol: str, client: BinanceClient) -> None:
    try:
        c = get_symbol_constraints(symbol, client)
    except Exception:
        return  # non-fatal — just skip the hint

    console.print(
        f"\n[dim]  {symbol} rules → "
        f"min qty: [cyan]{c['min_qty']}[/cyan]  "
        f"step: [cyan]{c['step_size']}[/cyan]  "
        f"tick: [cyan]{c['tick_size']}[/cyan]  "
        f"min notional: [cyan]${c['min_notional']}[/cyan][/dim]"
    )

ORDER_TYPE_CHOICES = {
    "1": "MARKET",
    "2": "LIMIT",
    "3": "STOP_MARKET",
}

SIDE_CHOICES = {
    "1": "BUY",
    "2": "SELL",
}


def prompt_order_type() -> str:
    console.print("\n[bold]Order type[/bold]")
    for k, v in ORDER_TYPE_CHOICES.items():
        console.print(f"  [cyan]{k}[/cyan]  {v}")
    while True:
        choice = Prompt.ask("Choose", choices=list(ORDER_TYPE_CHOICES.keys()))
        return ORDER_TYPE_CHOICES[choice]


def prompt_side() -> str:
    console.print("\n[bold]Side[/bold]")
    for k, v in SIDE_CHOICES.items():
        colour = "green" if v == "BUY" else "red"
        console.print(f"  [cyan]{k}[/cyan]  [{colour}]{v}[/{colour}]")
    while True:
        choice = Prompt.ask("Choose", choices=list(SIDE_CHOICES.keys()))
        return SIDE_CHOICES[choice]


@app.command("place")
def place_command(
    symbol: str = typer.Option(
        ..., "--symbol","-s",
        help="Trading pair, e.g. BTCUSDT",
        prompt="Symbol (e.g. BTCUSDT)",
    ),
    side: str = typer.Option(
        ..., "--side",
        help="BUY or SELL",
        prompt="Side (BUY/SELL)",
    ),
    order_type: str = typer.Option(
        ..., "--type","-t",
        help="MARKET, LIMIT, or STOP_MARKET",
        prompt="Order type (MARKET/LIMIT/STOP_MARKET)",
    ),
    quantity: str = typer.Option(
        ...,"--quantity","-q",
        help="Quantity in base asset units (e.g. 0.001 for BTC)",
        prompt="Quantity",
    ),
    price: Optional[str] = typer.Option(
        None, "--price","-p",
        help="Limit price (required for LIMIT orders)",
    ),
    stop_price: Optional[str] = typer.Option(
        None, "--stop-price",
        help="Stop trigger price (required for STOP_MARKET orders)",
    ),
    time_in_force: str = typer.Option(
        "GTC", "--tif",
        help="Time in force: GTC, IOC, FOK (LIMIT orders only)",
    ),
    yes: bool = typer.Option(
        False,"--yes","-y",
        help="Skip confirmation prompt",
    ),
) -> None:
    """
      Market buy:
        python cli.py place -s BTCUSDT --side BUY -t MARKET -q 0.001 -y

      Limit sell:
        python cli.py place -s BTCUSDT --side SELL -t LIMIT -q 0.001 -p 50000.0

      Stop market:
        python cli.py place -s BTCUSDT --side SELL -t STOP_MARKET -q 0.001 --stop-price 59000.0
    """
    client = _make_client()

    # Prompt for price/stop if order type needs them but they weren't passed
    otype = order_type.upper().strip()
    if otype == "LIMIT" and not price:
        price = Prompt.ask("[cyan]Limit price[/cyan]")
    if otype == "STOP_MARKET" and not stop_price:
        stop_price = Prompt.ask("[cyan]Stop price[/cyan]")

    # Validate before showing summary
    errors = validate_order(
        {
            "symbol":     symbol,
            "side":       side,
            "order_type": otype,
            "quantity":   quantity,
            "price":      price,
            "stop_price": stop_price,
        },
        client,
    )

    if errors:
        print_validation_errors(errors)
        print_constraints(symbol.upper(), client)
        raise typer.Exit(code=1)

    # Show request summary and confirm
    print_request_summary(symbol, side, otype, quantity, price, stop_price)

    if not yes:
        confirmed = Confirm.ask("\nSend this order?", default=False)
        if not confirmed:
            console.print("[yellow]Order cancelled.[/yellow]")
            raise typer.Exit()

    # Place order
    logger.info(
        "CLI placing order: %s %s %s qty=%s price=%s stop=%s",
        side.upper(), otype, symbol.upper(), quantity, price, stop_price,
    )

    try:
        with console.status("[cyan]Sending order to Binance...[/cyan]"):
            if otype == "MARKET":
                result = place_market_order(client, symbol, side, quantity)
            elif otype == "LIMIT":
                assert price is not None
                result = place_limit_order(client, symbol, side, quantity, price, time_in_force)
            elif otype == "STOP_MARKET":
                assert stop_price is not None
                result = place_stop_market_order(client, symbol, side, quantity, stop_price)
            else:
                console.print(f"[red]Unknown order type: {otype}[/red]")
                raise typer.Exit(code=1)

    except ValueError as e:
        console.print(f"\n[bold red]Validation error:[/bold red] {e}")
        raise typer.Exit(code=1)

    except BinanceAPIError as e:
        console.print(Panel(
            f"[bold red]Binance rejected the order[/bold red]\n\n"
            f"Code:    [red]{e.code}[/red]\n"
            f"Message: {e.message}",
            border_style="red",
        ))
        logger.error("Order rejected: code=%s msg=%s", e.code, e.message)
        raise typer.Exit(code=1)

    except BinanceNetworkError as e:
        console.print(Panel(f"[bold red]Network error[/bold red]\n\n{e}",border_style="red"))
        logger.error("Network error during order: %s", e)
        raise typer.Exit(code=1)

    print_order_result(result)


@app.command("interactive")
def interactive_command() -> None:
    # Guided interactive mode — menu-driven order placement.
    client = _make_client()

    console.print(Panel(
        "[bold cyan]Binance Futures Testnet — Interactive Mode[/bold cyan]\n"
        "[dim]All orders are placed on the testnet. No real funds.[/dim]",
        border_style="cyan",
    ))

    while True:
        console.print("\n[bold]Main menu[/bold]")
        console.print("  [cyan]1[/cyan]  Place an order")
        console.print("  [cyan]2[/cyan]  Check symbol rules")
        console.print("  [cyan]q[/cyan]  Quit")

        choice = Prompt.ask("\nChoose", choices=["1", "2", "q"])

        if choice == "q":
            console.print("[dim]Goodbye.[/dim]")
            break

        elif choice == "2":
            symbol = Prompt.ask("Symbol").upper().strip()
            print_constraints(symbol, client)

        elif choice == "1":
            run_interactive_order(client)


def run_interactive_order(client: BinanceClient) -> None:

    console.print("\n[bold cyan]── New order ──[/bold cyan]")

    # ---- Symbol ----
    while True:
        symbol = Prompt.ask("Symbol (e.g. BTCUSDT)").upper().strip()
        _, err = __import__("bot.validators", fromlist=["validate_symbol"]).validate_symbol(symbol)
        if err:
            console.print(f"  [red]{err}[/red]")
        else:
            print_constraints(symbol, client)
            break

    side = prompt_side()

    order_type = prompt_order_type()

    while True:
        quantity = Prompt.ask("\n[cyan]Quantity[/cyan]")
        from bot.validators import validate_quantity
        _, err = validate_quantity(quantity, symbol, client)
        if err:
            console.print(f"  [red]{err}[/red]")
        else:
            break

    price      = None
    stop_price = None

    if order_type == "LIMIT":
        from bot.validators import validate_price
        while True:
            price = Prompt.ask("\n[cyan]Limit price[/cyan]")
            _, err = validate_price(price, symbol, client)
            if err:
                console.print(f"  [red]{err}[/red]")
            else:
                break

    elif order_type == "STOP_MARKET":
        from bot.validators import validate_price, validate_stop_price
        ref_price = Prompt.ask("\n[cyan]Reference price[/cyan] [dim](current market price, for direction check)[/dim]")

        while True:
            stop_price = Prompt.ask("[cyan]Stop trigger price[/cyan]")
            _, err = validate_stop_price(stop_price, ref_price, side, symbol, client)
            if err:
                console.print(f"  [red]{err}[/red]")
            else:
                break

    print_request_summary(symbol, side, order_type, quantity, price, stop_price)
    confirmed = Confirm.ask("\nSend this order?", default=False)

    if not confirmed:
        console.print("[yellow]Order cancelled.[/yellow]")
        return

    try:
        with console.status("[cyan]Sending order...[/cyan]"):
            if order_type == "MARKET":
                result = place_market_order(client, symbol, side, quantity)
            elif order_type == "LIMIT":
                assert price is not None
                result = place_limit_order(client, symbol, side, quantity, price)
            elif order_type == "STOP_MARKET":
                assert stop_price is not None
                result = place_stop_market_order(client, symbol, side, quantity, stop_price)

    except BinanceAPIError as e:
        console.print(Panel(
            f"[bold red]Binance rejected the order[/bold red]\n\n"
            f"Code: [red]{e.code}[/red]  Message: {e.message}",
            border_style="red",
        ))
        logger.error("Interactive order rejected: code=%s msg=%s", e.code, e.message)
        return

    except BinanceNetworkError as e:
        console.print(Panel(f"[bold red]Network error[/bold red]\n\n{e}",border_style="red",))
        logger.error("Interactive network error: %s", e)
        return

    print_order_result(result)

if __name__ == "__main__":
    app()