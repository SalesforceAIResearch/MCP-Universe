"""
Provides default configurations and utilities for logging.

This module defines constants for log levels, logger names, and formatting. It also
includes a dictionary-based logging configuration and a utility function for creating
loggers.
"""
import logging

LOGLEVEL = "INFO"
LOGGER_NAME = "MCPUniverse"
TRACE_LOGGER_NAME = "MCPUniverse.trace"
LOGGER_FORMAT = "%(asctime)s.%(msecs)03d %(process)s %(name)s %(levelname)s [%(funcName)s():%(lineno)s] %(message)s"
TRACE_LOGGER_FORMAT = "%(asctime)s.%(msecs)03d %(name)s %(message)s"
LOGGER_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

LOG_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "MCPUniverse": {
            "()": "logging.Formatter",
            "fmt": LOGGER_FORMAT,
            "datefmt": LOGGER_DATE_FORMAT,
        },
        "MCPUniverse_trace": {
            "()": "logging.Formatter",
            "fmt": TRACE_LOGGER_FORMAT,
            "datefmt": LOGGER_DATE_FORMAT,
        },
        "uvicorn": {
            "()": "uvicorn.logging.DefaultFormatter",
            "datefmt": LOGGER_DATE_FORMAT,
            "fmt": "%(asctime)s.%(msecs)03d %(name)s %(levelprefix)s %(message)s",
            "use_colors": None,
        },
        "uvicorn_access": {
            "()": "uvicorn.logging.AccessFormatter",
            "datefmt": LOGGER_DATE_FORMAT,
            "fmt": "%(asctime)s.%(msecs)03d %(name)s "
                   "%(levelprefix)s %(client_addr)s %(process)s - "
                   '"%(request_line)s" %(status_code)s',
            # noqa: E501
        },
    },
    "handlers": {
        "MCPUniverse": {
            "formatter": "MCPUniverse",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
        "MCPUniverse_trace": {
            "formatter": "MCPUniverse_trace",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
        "uvicorn": {
            "formatter": "uvicorn",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
        "uvicorn_access": {
            "formatter": "uvicorn_access",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
        },
    },
    "loggers": {
        "MCPUniverse": {"handlers": ["MCPUniverse"], "level": LOGLEVEL, "propagate": False},
        "MCPUniverse.trace": {"handlers": ["MCPUniverse_trace"], "level": LOGLEVEL, "propagate": False},
        "uvicorn": {"handlers": ["uvicorn"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"level": "INFO"},
        "uvicorn.access": {"handlers": ["uvicorn_access"], "level": "INFO", "propagate": False},
    },
}


def get_logger(name, level="INFO", handler=logging.StreamHandler()):
    """
    Creates and returns a logger with the specified name and configuration.

    Args:
        name: The name of the logger.
        level: The logging level threshold (default is "INFO").
        handler: The logging handler to use (default is StreamHandler).

    Returns:
        A configured logging.Logger instance.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    formatter = logging.Formatter(LOGGER_FORMAT)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger
