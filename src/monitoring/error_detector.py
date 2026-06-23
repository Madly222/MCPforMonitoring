"""
Error Detector and Processor.

Processes log events, matches against known patterns,
and triggers appropriate actions.
"""

import re
import hashlib
from typing import Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict

import yaml
from loguru import logger

from src.core.config import get_config, KNOWLEDGE_DIR
from src.monitoring.log_watcher import LogEvent, LogEventType


@dataclass
class ErrorPattern:
    """Known error pattern."""
    pattern: str
    service: str
    severity: str
    auto_fix: bool
    diagnosis: str
    commands: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    cooldown: int = 300  # seconds


@dataclass
class DetectedError:
    """Detected error with context."""
    event: LogEvent
    pattern: Optional[ErrorPattern]
    error_hash: str
    first_seen: datetime
    last_seen: datetime
    count: int = 1
    resolved: bool = False
    resolution: Optional[str] = None


class ErrorDetector:
    """
    Detects and processes errors from log events.
    
    Features:
    - Pattern matching against known errors
    - Deduplication within time window
    - Cooldown tracking for auto-fix
    """
    
    def __init__(self):
        self.config = get_config()
        self._patterns: dict[str, list[ErrorPattern]] = defaultdict(list)
        self._recent_errors: dict[str, DetectedError] = {}
        self._cooldowns: dict[str, datetime] = {}
        self._load_patterns()
    
    def _load_patterns(self):
        """Load error patterns from knowledge base."""
        patterns_file = KNOWLEDGE_DIR / "known_errors.yaml"
        
        if not patterns_file.exists():
            logger.warning(f"Known errors file not found: {patterns_file}")
            return
        
        try:
            with open(patterns_file) as f:
                data = yaml.safe_load(f) or {}
            
            for service, patterns in data.items():
                if not isinstance(patterns, list):
                    continue
                
                for p in patterns:
                    pattern = ErrorPattern(
                        pattern=p.get("pattern", ""),
                        service=service,
                        severity=p.get("severity", "warning"),
                        auto_fix=p.get("auto_fix", False),
                        diagnosis=p.get("diagnosis", ""),
                        commands=p.get("commands", []),
                        suggestions=p.get("suggestions", []),
                        cooldown=p.get("cooldown", 300)
                    )
                    self._patterns[service].append(pattern)
            
            total = sum(len(p) for p in self._patterns.values())
            logger.info(f"Loaded {total} error patterns for {len(self._patterns)} services")
            
        except Exception as e:
            logger.error(f"Failed to load error patterns: {e}")
    
    def _compute_error_hash(self, event: LogEvent) -> str:
        """Compute hash for error deduplication."""
        # Normalize the line (remove timestamps, PIDs, IPs)
        normalized = re.sub(r'\d{4}-\d{2}-\d{2}', 'DATE', event.line)
        normalized = re.sub(r'\d{2}:\d{2}:\d{2}', 'TIME', normalized)
        normalized = re.sub(r'\d+\.\d+\.\d+\.\d+', 'IP', normalized)
        normalized = re.sub(r'\[\d+\]', '[PID]', normalized)
        normalized = re.sub(r'port \d+', 'port PORT', normalized)
        
        key = f"{event.server_id}:{event.service_type}:{normalized}"
        return hashlib.md5(key.encode()).hexdigest()[:16]
    
    def _match_pattern(self, event: LogEvent) -> Optional[ErrorPattern]:
        """Find matching error pattern."""
        # Check service-specific patterns
        service_patterns = self._patterns.get(event.service_type, [])
        
        for pattern in service_patterns:
            try:
                if re.search(pattern.pattern, event.line, re.IGNORECASE):
                    return pattern
            except re.error as e:
                logger.warning(f"Invalid regex pattern: {pattern.pattern} - {e}")
        
        return None
    
    def _is_duplicate(self, error_hash: str) -> bool:
        """Check if error is duplicate within dedup window."""
        settings = self.config.load_settings()
        window = settings.error_processing.dedup_window_seconds
        
        if error_hash in self._recent_errors:
            error = self._recent_errors[error_hash]
            if datetime.now() - error.last_seen < timedelta(seconds=window):
                return True
        
        return False
    
    def _is_in_cooldown(self, error_hash: str, pattern: ErrorPattern) -> bool:
        """Check if error is in cooldown for auto-fix."""
        if error_hash not in self._cooldowns:
            return False
        
        cooldown_until = self._cooldowns[error_hash]
        return datetime.now() < cooldown_until
    
    def _set_cooldown(self, error_hash: str, seconds: int):
        """Set cooldown for error."""
        self._cooldowns[error_hash] = datetime.now() + timedelta(seconds=seconds)
    
    def process_event(self, event: LogEvent) -> Optional[DetectedError]:
        """
        Process log event and detect errors.
        
        Returns DetectedError if error detected and not duplicate.
        """
        # Only process errors and warnings
        if event.event_type not in (LogEventType.ERROR, LogEventType.WARNING):
            return None
        
        error_hash = self._compute_error_hash(event)
        
        # Check for duplicate
        if self._is_duplicate(error_hash):
            # Update existing error
            existing = self._recent_errors[error_hash]
            existing.last_seen = datetime.now()
            existing.count += 1
            logger.debug(f"Duplicate error (count={existing.count}): {error_hash}")
            return None
        
        # Match against known patterns
        pattern = self._match_pattern(event)
        
        # Create detected error
        detected = DetectedError(
            event=event,
            pattern=pattern,
            error_hash=error_hash,
            first_seen=datetime.now(),
            last_seen=datetime.now()
        )
        
        # Store for deduplication
        self._recent_errors[error_hash] = detected
        
        # Log detection
        if pattern:
            logger.info(f"Known error detected: {pattern.diagnosis[:50]}...")
        else:
            logger.info(f"Unknown error detected: {event.line[:50]}...")
        
        return detected
    
    def can_auto_fix(self, detected: DetectedError) -> bool:
        """Check if error can be auto-fixed."""
        if not detected.pattern:
            return False
        
        if not detected.pattern.auto_fix:
            return False
        
        if self._is_in_cooldown(detected.error_hash, detected.pattern):
            logger.debug(f"Error in cooldown: {detected.error_hash}")
            return False
        
        return True
    
    def get_fix_commands(self, detected: DetectedError) -> list[str]:
        """Get fix commands for detected error."""
        if not detected.pattern:
            return []
        
        return detected.pattern.commands
    
    def mark_fix_attempted(self, detected: DetectedError):
        """Mark that fix was attempted (set cooldown)."""
        if detected.pattern:
            self._set_cooldown(detected.error_hash, detected.pattern.cooldown)
    
    def mark_resolved(self, detected: DetectedError, resolution: str):
        """Mark error as resolved."""
        detected.resolved = True
        detected.resolution = resolution
        
        if detected.error_hash in self._recent_errors:
            self._recent_errors[detected.error_hash].resolved = True
            self._recent_errors[detected.error_hash].resolution = resolution
    
    def get_recent_errors(self, minutes: int = 60) -> list[DetectedError]:
        """Get errors from last N minutes."""
        cutoff = datetime.now() - timedelta(minutes=minutes)
        
        return [
            error for error in self._recent_errors.values()
            if error.last_seen > cutoff
        ]
    
    def get_unresolved_errors(self) -> list[DetectedError]:
        """Get all unresolved errors."""
        return [
            error for error in self._recent_errors.values()
            if not error.resolved
        ]
    
    def cleanup_old_errors(self, hours: int = 24):
        """Remove old errors from memory."""
        cutoff = datetime.now() - timedelta(hours=hours)
        
        to_remove = [
            hash for hash, error in self._recent_errors.items()
            if error.last_seen < cutoff
        ]
        
        for hash in to_remove:
            del self._recent_errors[hash]
        
        if to_remove:
            logger.debug(f"Cleaned up {len(to_remove)} old errors")
    
    def get_error_stats(self) -> dict[str, Any]:
        """Get error statistics."""
        errors = list(self._recent_errors.values())
        
        return {
            "total": len(errors),
            "unresolved": len([e for e in errors if not e.resolved]),
            "resolved": len([e for e in errors if e.resolved]),
            "by_severity": {
                "error": len([e for e in errors if e.event.event_type == LogEventType.ERROR]),
                "warning": len([e for e in errors if e.event.event_type == LogEventType.WARNING])
            },
            "by_server": {
                server: len([e for e in errors if e.event.server_id == server])
                for server in set(e.event.server_id for e in errors)
            }
        }


_error_detector: Optional[ErrorDetector] = None


def get_error_detector() -> ErrorDetector:
    """Get error detector singleton instance."""
    global _error_detector
    if _error_detector is None:
        _error_detector = ErrorDetector()
    return _error_detector
