"""Centralized logging bootstrap for the whole project.

Every module calls setup_logging() once at startup (or imports this module and
uses the default logger). Log destination is stderr by default; optionally a
file via CODEX_MANAGER_LOG_FILE or --log.

Level resolution order (first wins):
  1. Explicit function argument from CLI (--verbose/--quiet/--debug).
  2. Environment variable CODEX_MANAGER_LOG (DEBUG/INFO/WARNING/ERROR/OFF).
  3. Default: WARNING (quiet by default; the actual command output stairs on
     stdout via print, not through the logger).
"""

import logging
import logging.handlers
import os
import sys

_LOGGER_NAME = "codex_manager"
_ENV_VAR = "CODEX_MANAGER_LOG"
_configured = False
_default_level = "WARNING"


def _normalize_level(level):
    if level is None:
        return None
    lv = str(level).upper().strip()
    return {
        "DEBUG": "DEBUG",
        "INFO": "INFO",
        "WARNING": "WARNING",
        "WARN": "WARNING",
        "ERROR": "ERROR",
        "OFF": "OFF",
        "QUIET": "ERROR",   # alias
        "VERBOSE": "INFO",  # alias
    }.get(lv, "WARNING")


def setup_logging(level=None, log_file=None, name=_LOGGER_NAME):
    """Configure the project logger. Safe to call multiple times (idempotent).

    `level`: DEBUG / INFO / WARNING / ERROR / OFF (or aliases quiet/verbose).
    `log_file`: optional path; writes rotate (1 MB x 3).
    Returns the project logger instance.
    """
    global _configured, _default_level
    logger = logging.getLogger(name)

    resolved = _normalize_level(level)
    if resolved is None:
        resolved = _normalize_level(os.environ.get(_ENV_VAR))
    if resolved is None:
        resolved = "WARNING"

    if resolved == "OFF":
        logger.setLevel(logging.CRITICAL + 1)
        logger.propagate = False
        _configured = True
        return logger

    logger.setLevel(getattr(logging, resolved))

    if not _configured:
        # stderr handler: short format so we don't double the "ERROR:" prefix.
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.addHandler(sh)
        if log_file:
            fh = logging.handlers.RotatingFileHandler(
                str(log_file), maxBytes=1 * 1024 * 1024, backupCount=3, encoding="utf-8"
            )
            fh.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
            ))
            logger.addHandler(fh)
        _configured = True
        _default_level = resolved

    logger.propagate = False
    return logger


def get_logger(name=None):
    """Get a project sub-logger. Call setup_logging() first, or use this and
    rely on the WARNING default (no handlers attached yet)."""
    if name and name != _LOGGER_NAME:
        return logging.getLogger(f"{_LOGGER_NAME}.{name}")
    return logging.getLogger(_LOGGER_NAME)
