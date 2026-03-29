import logging
import sys
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


def get_logger(name: str) -> logging.Logger:
    """
    returns logger object to write to logs/trading_bot.log
    Format : YYYY-MM-DD HH:MM:SS | LEVEL | LOGGER_NAME | MESSAGE
    """
    logger: logging.Logger = logging.getLogger(name=name)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # DEBUG level, captures everything
    file_handler = logging.FileHandler(LOG_DIR / "trading_bot.log")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # INFO level, keeps terminal clean
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


    return logger