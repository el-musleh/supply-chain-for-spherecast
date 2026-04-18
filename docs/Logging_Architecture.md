# Logging Architecture

## Overview

Agnes 2.0 uses a unified logging infrastructure (`logging_config.py`) that provides dual-file logging, structured JSON format, and session-based tracking for debugging and audit trails.

## Architecture

### Dual-File Logging

**System Log** (`logs/system.log`)
- Global log file for all system events
- Rotates daily (7-day retention)
- JSON format for machine parsing
- Captures events from all components

**Session Logs** (`logs/sessions/session_<timestamp>_<id>.log`)
- Per-session log files for UI interactions
- 30-day retention
- JSON format with session context
- Enables debugging specific user sessions

### Log Format

**JSON Structure:**
```json
{
  "timestamp": "2026-04-18T17:05:04.258Z",
  "level": "INFO",
  "logger": "agnes.ui",
  "message": "Evaluation started",
  "source": {
    "file": "/path/to/agnes_ui.py",
    "line": 450,
    "function": "submit_handler"
  },
  "thread": 12345,
  "process": 67890,
  "session_id": "d52d6649",
  "ingredient_a": "vitamin-d3",
  "ingredient_b": "vitamin-d3",
  "verdict": "APPROVE",
  "confidence": 0.85
}
```

**Human-Readable Console Output:**
```
2026-04-18 17:05:04.258 INFO [d52d6649] [evaluation][complete] Evaluation completed (1250ms)
```

## Components

### 1. System Logger

```python
from logging_config import get_logger

logger = get_logger("ui")
logger.info("Evaluation started", extra={"ingredient_a": "vitamin-d3"})
```

**Features:**
- Always available (auto-initialized on import)
- Writes to `logs/system.log`
- Outputs to console in human-readable format
- Redacts sensitive data (API keys, emails, passwords)

### 2. Session Logger

```python
from logging_config import create_session_logger

session_logger = create_session_logger()
session_logger.info("User submitted evaluation")
session_logger.log_evaluation(
    ingredient_a="vitamin-d3",
    ingredient_b="vitamin-d3",
    verdict="APPROVE",
    confidence=0.85
)
```

**Features:**
- Per-session isolation (unique session ID)
- Writes to dedicated session file
- Mirrors to system log
- Specialized methods: `log_evaluation()`, `log_scraper()`
- Automatic cleanup on app shutdown

### 3. Context Manager for Timed Operations

```python
from logging_config import log_operation

with log_operation(logger, "evaluate", "rag"):
    result = evaluate_something()
# Automatically logs: "evaluate started" and "evaluate completed (1250ms)"
```

## Sensitive Data Redaction

The logging system automatically redacts sensitive information:

| Pattern | Redacted As |
|---------|-------------|
| OpenAI API keys (`sk-...`) | `[REDACTED_SK]` |
| Gemini API keys (`gemini-...`) | `[REDACTED_API_KEY]` |
| Email addresses | `[REDACTED_EMAIL]` |
| Passwords (`password=...`) | `password=[REDACTED]` |
| API keys (`api_key=...`) | `api_key=[REDACTED]` |

Redaction applies to:
- Log messages
- Extra fields
- All log levels

## Log Rotation

### System Log
- **Rotation**: Daily at midnight
- **Retention**: 7 days
- **File Pattern**: `system.log.YYYY-MM-DD`

### Session Logs
- **Rotation**: Manual cleanup via `cleanup_old_logs()`
- **Retention**: 30 days
- **File Pattern**: `session_YYYYMMDD_HHMMSS_<id>.log`

### Manual Cleanup

```python
from logging_config import cleanup_old_logs

deleted = cleanup_old_logs()
print(f"Deleted: {deleted['system']} system logs, {deleted['sessions']} session logs")
```

## Session Lifecycle

### 1. Session Creation
```python
session_logger = create_session_logger()
# Generates unique session ID (16 chars)
# Creates session file: logs/sessions/session_YYYYMMDD_HHMMSS_<id>.log
# Logs "session.started" event
```

### 2. Session Usage
```python
session_logger.info("User action", extra={"action": "submit"})
session_logger.log_evaluation(...)
session_logger.log_scraper(...)
```

### 3. Session Cleanup
```python
session_logger.close()
# Logs "session.ended" event with duration
# Closes file handle
# Removes handler from logger
```

**Automatic Cleanup:**
The Gradio UI (`agnes_ui.py`) registers `atexit` cleanup:
```python
atexit.register(_cleanup_on_exit)
```

## Usage Examples

### Basic Logging

```python
from logging_config import get_logger

logger = get_logger("my_component")
logger.info("Component initialized")
logger.warning("Rate limit approaching", extra={"requests_remaining": 5})
logger.error("API call failed", exc_info=True)
```

### Session Logging with Structured Data

```python
from logging_config import create_session_logger

session_logger = create_session_logger()

# Log evaluation
session_logger.log_evaluation(
    ingredient_a="vitamin-d3-cholecalciferol",
    ingredient_b="vitamin-d3-cholecalciferol",
    supplier_a="Prinova USA",
    supplier_b="PureBulk",
    verdict="APPROVE",
    confidence=0.92,
    docs_retrieved=3,
)

# Log scraper event
session_logger.log_scraper(
    url="https://supplier.com/coa.pdf",
    success=True,
    method="pdf_download",
    duration_ms=450.5,
    size_kb=1250,
)
```

### Context Manager for Operations

```python
from logging_config import log_operation

with log_operation(session_logger, "rag_search", "retrieval"):
    docs = hybrid_search(rag_index, query, top_k=5)
# Logs: "rag_search started" and "rag_search completed (450ms)"
```

## Log Locations

```
logs/
├── system.log              # Global system events (7-day retention)
└── sessions/
    ├── session_20260418_170504_d52d6649.log  # Session logs (30-day retention)
    ├── session_20260418_180230_a1b2c3d4.log
    └── ...
```

## Viewing Logs

### View System Log
```bash
tail -f logs/system.log
```

### View Session Log
```bash
# Find latest session
ls -lt logs/sessions/ | head -1

# View specific session
cat logs/sessions/session_20260418_170504_d52d6649.log | jq
```

### Filter by Level
```bash
# Only errors
grep '"level":"ERROR"' logs/system.log

# Only warnings
grep '"level":"WARNING"' logs/system.log
```

### Filter by Session
```bash
grep '"session_id":"d52d6649"' logs/system.log
```

## Integration with Gradio UI

The Gradio UI (`agnes_ui.py`) integrates logging:

1. **Startup**: Creates session logger on launch
2. **Evaluation**: Logs each evaluation with structured data
3. **URL Fetching**: Logs scraper events with success/failure
4. **Session Logs Tab**: Displays session logs in UI with filtering
5. **Download**: Allows exporting session logs for debugging

## Troubleshooting

### Logs Not Appearing
- Check directory permissions on `logs/`
- Verify `logging_config.py` is imported
- Check if log rotation deleted old logs

### Session ID Not Showing
- Ensure `create_session_logger()` is called
- Check if session logger is properly initialized
- Verify `session_id` is being passed in `extra` dict

### Sensitive Data Not Redacted
- Verify pattern matches in `SENSITIVE_PATTERNS`
- Check if `SensitiveDataFilter` is added to handlers
- Ensure redaction is applied to both message and extra fields

### Log Files Too Large
- Reduce retention period in configuration
- Run `cleanup_old_logs()` more frequently
- Adjust log level to WARNING or ERROR for verbose components

## Configuration

Edit `logging_config.py` to adjust:

```python
# Retention policies
SYSTEM_RETENTION_DAYS = 7
SESSION_RETENTION_DAYS = 30

# Sensitive patterns
SENSITIVE_PATTERNS = [
    (re.compile(r'sk-[a-zA-Z0-9]{20,}'), '[REDACTED_SK]'),
    # Add more patterns as needed
]

# Log levels
root_logger.setLevel(logging.DEBUG)  # Change to INFO for less verbosity
```

## Best Practices

1. **Use Structured Extra Fields**: Always use `extra={}` for structured data
2. **Log at Appropriate Levels**: DEBUG for details, INFO for events, WARNING for issues, ERROR for failures
3. **Include Context**: Add session_id, component, operation for traceability
4. **Redact Early**: Never log raw API keys or passwords
5. **Use Context Managers**: For operations with duration tracking
6. **Clean Up Sessions**: Always call `session_logger.close()` or use `atexit`
7. **Monitor Log Size**: Run cleanup regularly in production

## Production Considerations

### Centralized Logging
For production deployment, consider:
- Sending logs to centralized service (ELK, Datadog, CloudWatch)
- Using log aggregation for distributed tracing
- Implementing log sampling for high-volume events

### Performance
- Use async logging for high-throughput scenarios
- Batch log writes for external services
- Consider log level switching (DEBUG in dev, INFO in prod)

### Security
- Encrypt logs containing sensitive data
- Restrict log file permissions (chmod 600)
- Implement log retention policies for compliance
- Audit log access for security monitoring

## API Reference

### Functions

| Function | Purpose |
|----------|---------|
| `get_logger(name)` | Get system logger with specified name |
| `create_session_logger(id)` | Create new per-session logger |
| `get_session_logger()` | Get current session logger |
| `close_session_logger()` | Close current session logger |
| `cleanup_old_logs()` | Remove logs older than retention policy |
| `log_operation(logger, op, comp)` | Context manager for timed operations |

### Classes

| Class | Purpose |
|-------|---------|
| `SessionLogger` | Per-session logging with specialized methods |
| `JSONFormatter` | Format logs as JSON |
| `HumanFormatter` | Format logs for console output |
| `SensitiveDataFilter` | Redact sensitive information from logs |
