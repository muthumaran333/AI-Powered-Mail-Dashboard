import logging
from .config_loader import config


def get_logger(name: str = "app"):
    """
    Create a logger with custom StreamHandler and Formatter.
    Uses LOG_LEVEL from config (default INFO).
    """
    logger = logging.getLogger(name)

    # Avoid adding handlers multiple times if logger already exists
    if not logger.handlers:
        log_level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
        logger.setLevel(log_level)

        # Create console handler
        ch = logging.StreamHandler()
        ch.setLevel(log_level)

        # Define log format with module name
        formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
        )
        ch.setFormatter(formatter)

        # Add handler
        logger.addHandler(ch)

    return logger


# Default logger for general use (logger name = module where it's defined)
logger = get_logger(__name__)
