"""
logging_config.py — Unified logging infrastructure for Agnes 2.0

Features:
  • Dual-file logging: system.log (all events) + session_<id>.log (per-session)
  • Structured JSON format for machine parsing
  • Human-readable format for debugging
  • Log rotation (7 days system, 30 days sessions)
  • Sensitive data redaction (API keys, credentials)
  • Session ID propagation across components

Usage:
    from logging_config import get_logger, create_session_logger
    
    # System-wide logging (always available)
    logger = get_logger("agnes.ui")
    logger.info("Evaluation started", extra={"ingredient_a": "vitamin-d3"})
    
    # Per-session logging (created at UI launch)
    session_logger = create_session_logger()
    session_logger.info("User submitted evaluation")
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

LOGS_DIR = Path(__file__).parent / "logs"
SESSIONS_DIR = LOGS_DIR / "sessions"
SYSTEM_LOG = LOGS_DIR / "system.log"

# Retention policies
SYSTEM_RETENTION_DAYS = 7
SESSION_RETENTION_DAYS = 30

# Patterns to redact from logs
SENSITIVE_PATTERNS = [
    (re.compile(r'sk-[a-zA-Z0-9]{20,}'), '[REDACTED_SK]'),
    (re.compile(r'gemini-[a-zA-Z0-9_-]{20,}'), '[REDACTED_API_KEY]'),
    (re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'), '[REDACTED_EMAIL]'),
    (re.compile(r'password[=:]\s*\S+', re.IGNORECASE), 'password=[REDACTED]'),
    (re.compile(r'api[_-]?key[=:]\s*\S+', re.IGNORECASE), 'api_key=[REDACTED]'),
]

# ─────────────────────────────────────────────────────────────────────────────
# Sensitive Data Filter
# ─────────────────────────────────────────────────────────────────────────────

class SensitiveDataFilter(logging.Filter):
    """Filter that redacts sensitive information from log records."""
    
    def filter(self, record: logging.LogRecord) -> bool:
        # Redact from message
        msg = str(record.getMessage())
        for pattern, replacement in SENSITIVE_PATTERNS:
            msg = pattern.sub(replacement, msg)
        record.msg = msg
        
        # Redact from extra fields if present
        if hasattr(record, 'extra'):
            for key, value in record.extra.items():
                if isinstance(value, str):
                    for pattern, replacement in SENSITIVE_PATTERNS:
                        value = pattern.sub(replacement, value)
                    record.extra[key] = value
        
        return True


# ─────────────────────────────────────────────────────────────────────────────
# JSON Formatter for Structured Logging
# ─────────────────────────────────────────────────────────────────────────────

class JSONFormatter(logging.Formatter):
    """Format log records as JSON for machine parsing."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "source": {
                "file": record.pathname,
                "line": record.lineno,
                "function": record.funcName,
            },
            "thread": record.thread,
            "process": record.process,
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields
        for attr in ['session_id', 'ingredient_a', 'ingredient_b', 'supplier', 
                     'verdict', 'confidence', 'component', 'operation', 'duration_ms']:
            if hasattr(record, attr):
                log_data[attr] = getattr(record, attr)
        
        # Add any custom extra fields
        if hasattr(record, 'extra'):
            log_data.update(record.extra)
        
        return json.dumps(log_data, default=str)


class HumanFormatter(logging.Formatter):
    """Format log records for human-readable console output."""
    
    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        level = record.levelname[:4]
        
        # Include session_id if present
        session_tag = ""
        if hasattr(record, 'session_id'):
            session_id = record.session_id[:8]
            session_tag = f"[{session_id}] "
        
        # Include component/operation if present
        context = ""
        if hasattr(record, 'component'):
            context = f"[{record.component}]"
        if hasattr(record, 'operation'):
            context += f"[{record.operation}]" if context else f"[{record.operation}]"
        if context:
            context = f"{context} "
        
        msg = record.getMessage()
        
        # Add duration if present
        if hasattr(record, 'duration_ms'):
            msg += f" ({record.duration_ms}ms)"
        
        return f"{timestamp} {level} {session_tag}{context}{msg}"


# ─────────────────────────────────────────────────────────────────────────────
# Session Logger
# ─────────────────────────────────────────────────────────────────────────────

class SessionLogger:
    """
    Per-session logger that writes to both system.log and a dedicated session file.
    """
    
    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or str(uuid.uuid4())[:16]
        self.session_start = datetime.now(timezone.utc)
        self.logger = logging.getLogger(f"agnes.session.{self.session_id}")
        self.logger.setLevel(logging.DEBUG)
        
        # Prevent propagation to avoid duplicate logs
        self.logger.propagate = False
        
        # Ensure directories exist
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        
        # Create session file handler
        timestamp = self.session_start.strftime('%Y%m%d_%H%M%S')
        session_file = SESSIONS_DIR / f"session_{timestamp}_{self.session_id}.log"
        
        # Session file handler (JSON format for structured data)
        session_handler = logging.FileHandler(session_file, encoding='utf-8')
        session_handler.setFormatter(JSONFormatter())
        session_handler.addFilter(SensitiveDataFilter())
        
        # Also log to system log via the system logger
        self.logger.addHandler(session_handler)
        
        # Store reference for cleanup
        self._session_file = session_file
        self._session_handler = session_handler
        
        self._log("session", "started", {
            "session_id": self.session_id,
            "session_file": str(session_file),
            "python_version": sys.version,
        })
    
    def _log(self, component: str, operation: str, extra: dict | None = None):
        """Internal logging with session context."""
        extra = extra or {}
        extra.update({
            "session_id": self.session_id,
            "component": component,
            "operation": operation,
        })
        
        # Create a LogRecord with extra fields
        record = self.logger.makeRecord(
            self.logger.name,
            logging.INFO,
            "(session)",
            0,
            f"{component}.{operation}",
            (),
            None,
            extra=extra
        )
        
        # Add extra fields to record
        for key, value in extra.items():
            setattr(record, key, value)
        
        self.logger.handle(record)
        
        # Also log to system logger
        system_logger = get_logger(f"agnes.session.{self.session_id}")
        system_logger.handle(record)
    
    def info(self, message: str, extra: dict | None = None):
        """Log info level message."""
        extra = extra or {}
        extra['session_id'] = self.session_id
        self.logger.info(message, extra=extra)
        
        # Mirror to system log
        system_logger = get_logger("agnes.ui")
        system_logger.info(message, extra=extra)
    
    def debug(self, message: str, extra: dict | None = None):
        """Log debug level message."""
        extra = extra or {}
        extra['session_id'] = self.session_id
        self.logger.debug(message, extra=extra)
        
        system_logger = get_logger("agnes.ui")
        system_logger.debug(message, extra=extra)
    
    def warning(self, message: str, extra: dict | None = None):
        """Log warning level message."""
        extra = extra or {}
        extra['session_id'] = self.session_id
        extra['level'] = 'WARNING'
        self.logger.warning(message, extra=extra)
        
        system_logger = get_logger("agnes.ui")
        system_logger.warning(message, extra=extra)
    
    def error(self, message: str, extra: dict | None = None, exc_info: bool = False):
        """Log error level message."""
        extra = extra or {}
        extra['session_id'] = self.session_id
        extra['level'] = 'ERROR'
        self.logger.error(message, extra=extra, exc_info=exc_info)
        
        system_logger = get_logger("agnes.ui")
        system_logger.error(message, extra=extra, exc_info=exc_info)
    
    def log_evaluation(self, ingredient_a: str, ingredient_b: str, 
                       verdict: str, confidence: float, **kwargs):
        """Log an evaluation event with structured data."""
        extra = {
            'session_id': self.session_id,
            'component': 'evaluation',
            'operation': 'complete',
            'ingredient_a': ingredient_a,
            'ingredient_b': ingredient_b,
            'verdict': verdict,
            'confidence': confidence,
            **kwargs
        }
        self.logger.info("Evaluation completed", extra=extra)
        
        system_logger = get_logger("agnes.evaluation")
        system_logger.info("Evaluation completed", extra=extra)
    
    def log_scraper(self, url: str, success: bool, method: str, 
                    duration_ms: float, **kwargs):
        """Log a scraper event."""
        extra = {
            'session_id': self.session_id,
            'component': 'scraper',
            'operation': 'fetch',
            'url': url[:200],  # Truncate long URLs
            'success': success,
            'method': method,
            'duration_ms': duration_ms,
            **kwargs
        }
        level = logging.INFO if success else logging.WARNING
        self.logger.log(level, f"Scraper {method} {'success' if success else 'failed'}", extra=extra)
        
        system_logger = get_logger("agnes.scraper")
        system_logger.log(level, f"Scraper fetch completed", extra=extra)
    
    def close(self):
        """Close the session logger and cleanup."""
        duration = (datetime.now(timezone.utc) - self.session_start).total_seconds()
        self._log("session", "ended", {"duration_seconds": duration})
        
        self._session_handler.close()
        self.logger.removeHandler(self._session_handler)
    
    @property
    def session_file_path(self) -> Path:
        """Return the path to this session's log file."""
        return self._session_file


# ─────────────────────────────────────────────────────────────────────────────
# Global Logger Setup
# ─────────────────────────────────────────────────────────────────────────────

_SESSION_LOGGER: SessionLogger | None = None

def setup_logging() -> None:
    """Initialize the global logging configuration."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Root logger configuration
    root_logger = logging.getLogger("agnes")
    root_logger.setLevel(logging.DEBUG)
    
    # Prevent duplicate handlers
    if root_logger.handlers:
        return
    
    # System log file handler (rotating)
    system_handler = logging.handlers.TimedRotatingFileHandler(
        SYSTEM_LOG,
        when='midnight',
        interval=1,
        backupCount=SYSTEM_RETENTION_DAYS,
        encoding='utf-8'
    )
    system_handler.setFormatter(JSONFormatter())
    system_handler.addFilter(SensitiveDataFilter())
    system_handler.setLevel(logging.DEBUG)
    
    # Console handler (human-readable)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(HumanFormatter())
    console_handler.addFilter(SensitiveDataFilter())
    console_handler.setLevel(logging.INFO)
    
    root_logger.addHandler(system_handler)
    root_logger.addHandler(console_handler)
    
    # Log startup
    root_logger.info("Logging system initialized", extra={
        'system_log': str(SYSTEM_LOG),
        'logs_dir': str(LOGS_DIR),
    })


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the specified name."""
    setup_logging()
    return logging.getLogger(f"agnes.{name}")


def create_session_logger(session_id: str | None = None) -> SessionLogger:
    """Create a new per-session logger."""
    global _SESSION_LOGGER
    setup_logging()
    
    # Close existing session if any
    if _SESSION_LOGGER is not None:
        _SESSION_LOGGER.close()
    
    _SESSION_LOGGER = SessionLogger(session_id)
    return _SESSION_LOGGER


def get_session_logger() -> SessionLogger | None:
    """Get the current session logger if one exists."""
    return _SESSION_LOGGER


def close_session_logger() -> None:
    """Close the current session logger."""
    global _SESSION_LOGGER
    if _SESSION_LOGGER is not None:
        _SESSION_LOGGER.close()
        _SESSION_LOGGER = None


# ─────────────────────────────────────────────────────────────────────────────
# Log Cleanup
# ─────────────────────────────────────────────────────────────────────────────

def cleanup_old_logs() -> dict[str, int]:
    """
    Remove log files older than retention policy.
    Returns count of deleted files by category.
    """
    import time
    
    deleted = {"system": 0, "sessions": 0}
    now = time.time()
    
    # Cleanup old session logs
    if SESSIONS_DIR.exists():
        for log_file in SESSIONS_DIR.glob("session_*.log"):
            age_days = (now - log_file.stat().st_mtime) / 86400
            if age_days > SESSION_RETENTION_DAYS:
                log_file.unlink()
                deleted["sessions"] += 1
    
    # Cleanup old system logs (handled by TimedRotatingFileHandler, but just in case)
    if LOGS_DIR.exists():
        for log_file in LOGS_DIR.glob("system.log.*"):
            age_days = (now - log_file.stat().st_mtime) / 86400
            if age_days > SYSTEM_RETENTION_DAYS:
                log_file.unlink()
                deleted["system"] += 1
    
    return deleted


# ─────────────────────────────────────────────────────────────────────────────
# Context Manager for Timed Operations
# ─────────────────────────────────────────────────────────────────────────────

from contextlib import contextmanager
from time import perf_counter

@contextmanager
def log_operation(logger: logging.Logger, operation: str, component: str = ""):
    """
    Context manager for logging operations with duration.
    
    Usage:
        with log_operation(logger, "evaluate", "rag"):
            result = evaluate_something()
    """
    start = perf_counter()
    extra = {
        'operation': operation,
        'component': component,
    }
    
    if hasattr(logger, 'session_id'):
        extra['session_id'] = logger.session_id
    
    logger.info(f"{operation} started", extra=extra)
    
    try:
        yield
        duration = (perf_counter() - start) * 1000
        extra['duration_ms'] = round(duration, 2)
        extra['status'] = 'success'
        logger.info(f"{operation} completed", extra=extra)
    except Exception as e:
        duration = (perf_counter() - start) * 1000
        extra['duration_ms'] = round(duration, 2)
        extra['status'] = 'error'
        extra['error'] = str(e)
        logger.error(f"{operation} failed", extra=extra, exc_info=True)
        raise


# Initialize on module import
setup_logging()
