

"""
logger.py
PURPOSE: Structured logging for the system.
"""

import os
import sys
import json
import time
import logging
from typing import Any, Dict, Optional
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LogEntry:
    """Structured log entry."""
    timestamp: float
    level: str
    category: str
    message: str
    context: Dict[str, Any]
    
    def to_json(self) -> str:
        return json.dumps({
            'ts': self.timestamp,
            'level': self.level,
            'cat': self.category,
            'msg': self.message,
            **self.context
        })
    
    def to_text(self) -> str:
        ctx_str = ' '.join(f'{k}={v}' for k, v in self.context.items())
        ts_str = time.strftime('%H:%M:%S', time.localtime(self.timestamp))
        return f"[{ts_str}] [{self.level:5}] [{self.category:12}] {self.message} {ctx_str}"


class StructuredLogger:
    """
    Structured logger with category-based filtering.
    
    Features:
        - Category-based log filtering
        - JSON or text output
        - File and console output
        - Context injection
    """
    
    LEVELS = {'DEBUG': 10, 'INFO': 20, 'WARNING': 30, 'ERROR': 40, 'CRITICAL': 50}
    
    def __init__(
        self,
        log_file: Optional[str] = None,
        log_level: str = "INFO",
        json_format: bool = False,
        console_output: bool = True
    ):
        """
        Initialize logger.
        
        Args:
            log_file: Path to log file. None for console only.
            log_level: Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            json_format: Use JSON format instead of text
            console_output: Also write to console
        """
        self.log_level = self.LEVELS.get(log_level.upper(), 20)
        self.json_format = json_format
        self.console_output = console_output
        self._file_handle = None
        self._context: Dict[str, Any] = {}
        
        # Category-specific levels
        self._category_levels: Dict[str, int] = {}
        
        if log_file:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            self._file_handle = open(log_file, 'a')
    
    def set_category_level(self, category: str, level: str) -> None:
        """Set log level for a specific category."""
        self._category_levels[category] = self.LEVELS.get(level.upper(), 20)
    
    def set_context(self, **kwargs) -> None:
        """Set persistent context fields."""
        self._context.update(kwargs)
    
    def clear_context(self) -> None:
        """Clear all context fields."""
        self._context.clear()
    
    def _should_log(self, level: str, category: str) -> bool:
        """Check if this message should be logged."""
        level_num = self.LEVELS.get(level, 20)
        min_level = self._category_levels.get(category, self.log_level)
        return level_num >= min_level
    
    def _log(
        self,
        level: str,
        category: str,
        message: str,
        **kwargs
    ) -> None:
        """Internal log method."""
        if not self._should_log(level, category):
            return
        
        context = {**self._context, **kwargs}
        entry = LogEntry(
            timestamp=time.time(),
            level=level,
            category=category,
            message=message,
            context=context
        )
        
        output = entry.to_json() if self.json_format else entry.to_text()
        
        if self.console_output:
            print(output, file=sys.stderr)
        
        if self._file_handle:
            self._file_handle.write(output + '\n')
            self._file_handle.flush()
    
    def debug(self, category: str, message: str, **kwargs) -> None:
        self._log('DEBUG', category, message, **kwargs)
    
    def info(self, category: str, message: str, **kwargs) -> None:
        self._log('INFO', category, message, **kwargs)
    
    def warning(self, category: str, message: str, **kwargs) -> None:
        self._log('WARNING', category, message, **kwargs)
    
    def error(self, category: str, message: str, **kwargs) -> None:
        self._log('ERROR', category, message, **kwargs)
    
    def critical(self, category: str, message: str, **kwargs) -> None:
        self._log('CRITICAL', category, message, **kwargs)
    
    def close(self) -> None:
        """Close log file handle."""
        if self._file_handle:
            self._file_handle.close()
            self._file_handle = None


# Global logger instance
_logger: Optional[StructuredLogger] = None


def get_logger() -> StructuredLogger:
    """Get global logger instance."""
    global _logger
    if _logger is None:
        _logger = StructuredLogger()
    return _logger


def configure_logger(
    log_file: Optional[str] = None,
    log_level: str = "INFO",
    json_format: bool = False
) -> StructuredLogger:
    """Configure and return global logger."""
    global _logger
    _logger = StructuredLogger(
        log_file=log_file,
        log_level=log_level,
        json_format=json_format
    )
    return _logger


# Convenience functions
def log_debug(category: str, message: str, **kwargs) -> None:
    get_logger().debug(category, message, **kwargs)


def log_info(category: str, message: str, **kwargs) -> None:
    get_logger().info(category, message, **kwargs)


def log_warning(category: str, message: str, **kwargs) -> None:
    get_logger().warning(category, message, **kwargs)


def log_error(category: str, message: str, **kwargs) -> None:
    get_logger().error(category, message, **kwargs)
