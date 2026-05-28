"""
Structured logging setup.

Provides a consistent, configurable logger for the entire application.
Log level is controlled via the LOG_LEVEL environment variable.
"""

import logging
import sys


def setup_logger(name: str = "bill_processor", level: str = "INFO") -> logging.Logger:
    """Create and configure an application logger.

    Args:
        name: Logger name (used as the logger hierarchy root).
        level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).

    Returns:
        Configured Logger instance.
    """
    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers on repeated calls
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Console handler with structured format
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s.%(funcName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


def get_logger(module_name: str = "bill_processor") -> logging.Logger:
    """Get a child logger for a specific module.

    Usage:
        from src.utils.logger import get_logger
        logger = get_logger(__name__)
        logger.info("Starting extraction...")
    """
    return logging.getLogger(f"bill_processor.{module_name}")
