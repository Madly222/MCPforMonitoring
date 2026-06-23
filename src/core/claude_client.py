"""
Claude API Client.

Provides integration with Claude API for:
- Error analysis
- Natural language command interpretation
- Intelligent diagnostics
"""

import json
import re
import hashlib
from typing import Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field

from anthropic import Anthropic
from loguru import logger

from src.core.config import get_config


@dataclass
class AnalysisResult:
    """Result of Claude analysis."""
    diagnosis: str
    severity: str
    can_auto_fix: bool
    fix_commands: list[str]
    needs_human: bool
    reason: Optional[str] = None
    suggestions: list[str] = field(default_factory=list)


@dataclass
class CommandInterpretation:
    """Interpreted command from natural language."""
    intent: str
    server_id: Optional[str]
    service_type: Optional[str]
    action: Optional[str]
    parameters: dict = field(default_factory=dict)
    raw_command: Optional[str] = None
    confidence: float = 1.0


@dataclass
class CacheEntry:
    """Cache entry for API responses."""
    response: Any
    created_at: datetime


class ClaudeClient:
    """
    Client for Claude API interactions.
    
    Features:
    - Error analysis
    - Command interpretation
    - Response caching
    - Rate limiting
    """
    
    SYSTEM_PROMPT_ANALYSIS = """You are a Linux server diagnostic assistant.
Analyze the provided error logs and system information.

Your response must be valid JSON with this exact structure:
{{
    "diagnosis": "Brief explanation of the problem",
    "severity": "critical|warning|info",
    "can_auto_fix": true|false,
    "fix_commands": ["command1", "command2"],
    "needs_human": true|false,
    "reason": "Why human intervention needed (if applicable)",
    "suggestions": ["suggestion1", "suggestion2"]
}}

Rules:
- Be concise and precise
- Only suggest safe commands
- Set can_auto_fix=true only for safe operations like service restart
- Set needs_human=true for config changes, data deletion, or unclear issues
- Always provide actionable suggestions"""

    SYSTEM_PROMPT_COMMAND = """You are a server management assistant.
Interpret the user's natural language command and extract the intent.

Available servers: {servers}
Available services: dhcp, dns, postfix, dovecot, apache, spamfilter
Available actions: status, start, stop, restart, reload, logs, config, diagnostics

Your response must be valid JSON with this exact structure:
{{
    "intent": "check_status|restart_service|get_logs|show_config|run_diagnostic|unknown",
    "server_id": "server-name or null for all",
    "service_type": "dhcp|dns|postfix|etc or null",
    "action": "specific action or null",
    "parameters": {{}},
    "raw_command": "shell command if applicable",
    "confidence": 0.0-1.0
}}

Rules:
- Extract server name if mentioned
- Extract service type if mentioned
- Set confidence based on how clear the request is
- For ambiguous requests, set intent=unknown and ask for clarification"""

    def __init__(self):
        self.config = get_config()
        self._client: Optional[Anthropic] = None
        self._cache: dict[str, CacheEntry] = {}
        self._request_times: list[datetime] = []
    
    @property
    def client(self) -> Anthropic:
        """Get or create Anthropic client."""
        if self._client is None:
            secrets = self.config.load_secrets()
            self._client = Anthropic(api_key=secrets.claude.api_key)
        return self._client
    
    def _get_cache_key(self, prompt: str) -> str:
        """Generate cache key for prompt."""
        return hashlib.md5(prompt.encode()).hexdigest()
    
    def _get_cached(self, key: str) -> Optional[Any]:
        """Get cached response if valid."""
        if key not in self._cache:
            return None
        
        entry = self._cache[key]
        settings = self.config.load_settings()
        ttl_hours = settings.claude_optimization.cache.ttl_hours
        
        if datetime.now() - entry.created_at > timedelta(hours=ttl_hours):
            del self._cache[key]
            return None
        
        return entry.response
    
    def _set_cached(self, key: str, response: Any):
        """Cache response."""
        self._cache[key] = CacheEntry(
            response=response,
            created_at=datetime.now()
        )
    
    def _check_rate_limit(self) -> bool:
        """Check if we're within rate limits."""
        settings = self.config.load_settings()
        now = datetime.now()
        
        # Clean old entries
        minute_ago = now - timedelta(minutes=1)
        hour_ago = now - timedelta(hours=1)
        
        self._request_times = [t for t in self._request_times if t > hour_ago]
        
        # Check limits
        requests_last_minute = sum(1 for t in self._request_times if t > minute_ago)
        requests_last_hour = len(self._request_times)
        
        max_per_minute = settings.claude_optimization.rate_limit.max_requests_per_minute
        max_per_hour = settings.claude_optimization.rate_limit.max_requests_per_hour
        
        if requests_last_minute >= max_per_minute:
            logger.warning(f"Rate limit: {requests_last_minute}/{max_per_minute} per minute")
            return False
        
        if requests_last_hour >= max_per_hour:
            logger.warning(f"Rate limit: {requests_last_hour}/{max_per_hour} per hour")
            return False
        
        return True
    
    def _record_request(self):
        """Record API request for rate limiting."""
        self._request_times.append(datetime.now())
    
    async def analyze_error(
        self,
        error_lines: list[str],
        server_info: dict,
        context_lines: Optional[list[str]] = None
    ) -> AnalysisResult:
        """
        Analyze error using Claude API.
        
        Args:
            error_lines: Error log lines
            server_info: Server information dict
            context_lines: Additional context lines
            
        Returns:
            AnalysisResult with diagnosis and recommendations
        """
        # Build prompt
        prompt = f"""Server: {server_info.get('server_id', 'unknown')}
Distro: {server_info.get('distro', 'unknown')}
Services: {', '.join(server_info.get('services', []))}
Init System: {server_info.get('init_system', 'unknown')}

Error lines:
{chr(10).join(error_lines[-20:])}
"""
        
        if context_lines:
            prompt += f"""
Context:
{chr(10).join(context_lines[-30:])}
"""
        
        # Check cache
        cache_key = self._get_cache_key(prompt)
        cached = self._get_cached(cache_key)
        if cached:
            logger.debug("Using cached analysis")
            return cached
        
        # Check rate limit
        if not self._check_rate_limit():
            return AnalysisResult(
                diagnosis="Rate limit exceeded, please try again later",
                severity="info",
                can_auto_fix=False,
                fix_commands=[],
                needs_human=True,
                reason="API rate limit"
            )
        
        try:
            secrets = self.config.load_secrets()
            
            self._record_request()
            
            response = self.client.messages.create(
                model=secrets.claude.model,
                max_tokens=secrets.claude.max_tokens,
                system=self.SYSTEM_PROMPT_ANALYSIS,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            # Parse response
            content = response.content[0].text
            
            # Try to extract JSON
            try:
                # Handle potential markdown code blocks and extract JSON
                json_str = content.strip()
                
                # Try to find JSON in markdown code block
                if "```json" in json_str:
                    json_str = json_str.split("```json")[1].split("```")[0]
                elif "```" in json_str:
                    parts = json_str.split("```")
                    for part in parts:
                        part = part.strip()
                        if part.startswith("{"):
                            json_str = part
                            break
                
                # Try to find JSON object directly
                if not json_str.startswith("{"):
                    match = re.search(r'\{[^{}]*\}', json_str, re.DOTALL)
                    if match:
                        json_str = match.group(0)
                
                # Handle nested braces properly
                brace_count = 0
                start_idx = None
                for i, char in enumerate(json_str):
                    if char == '{':
                        if start_idx is None:
                            start_idx = i
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0 and start_idx is not None:
                            json_str = json_str[start_idx:i+1]
                            break
                
                data = json.loads(json_str)
                
                result = AnalysisResult(
                    diagnosis=data.get("diagnosis", "Unable to analyze"),
                    severity=data.get("severity", "warning"),
                    can_auto_fix=data.get("can_auto_fix", False),
                    fix_commands=data.get("fix_commands", []),
                    needs_human=data.get("needs_human", True),
                    reason=data.get("reason"),
                    suggestions=data.get("suggestions", [])
                )
                
                # Cache result
                self._set_cached(cache_key, result)
                
                logger.info(f"Claude analysis: {result.diagnosis[:50]}...")
                
                return result
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse Claude response: {e}")
                return AnalysisResult(
                    diagnosis=content[:200],
                    severity="warning",
                    can_auto_fix=False,
                    fix_commands=[],
                    needs_human=True,
                    reason="Could not parse structured response"
                )
                
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            return AnalysisResult(
                diagnosis=f"API error: {str(e)}",
                severity="warning",
                can_auto_fix=False,
                fix_commands=[],
                needs_human=True,
                reason=str(e)
            )
    
    async def interpret_command(
        self,
        command: str,
        available_servers: list[str]
    ) -> CommandInterpretation:
        """
        Interpret natural language command.
        
        Args:
            command: Natural language command from user
            available_servers: List of available server IDs
            
        Returns:
            CommandInterpretation with extracted intent and parameters
        """
        system_prompt = self.SYSTEM_PROMPT_COMMAND.format(
            servers=", ".join(available_servers)
        )
        
        # Check cache
        cache_key = self._get_cache_key(f"cmd:{command}")
        cached = self._get_cached(cache_key)
        if cached:
            logger.debug("Using cached interpretation")
            return cached
        
        # Check rate limit
        if not self._check_rate_limit():
            return CommandInterpretation(
                intent="error",
                server_id=None,
                service_type=None,
                action=None,
                confidence=0.0
            )
        
        try:
            secrets = self.config.load_secrets()
            
            self._record_request()
            
            response = self.client.messages.create(
                model=secrets.claude.model,
                max_tokens=512,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": command}
                ]
            )
            
            content = response.content[0].text
            
            try:
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0]
                
                data = json.loads(content.strip())
                
                result = CommandInterpretation(
                    intent=data.get("intent", "unknown"),
                    server_id=data.get("server_id"),
                    service_type=data.get("service_type"),
                    action=data.get("action"),
                    parameters=data.get("parameters", {}),
                    raw_command=data.get("raw_command"),
                    confidence=data.get("confidence", 0.5)
                )
                
                # Cache result
                self._set_cached(cache_key, result)
                
                logger.info(f"Command interpreted: intent={result.intent}, server={result.server_id}")
                
                return result
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse command interpretation: {e}")
                return CommandInterpretation(
                    intent="unknown",
                    server_id=None,
                    service_type=None,
                    action=None,
                    confidence=0.0
                )
                
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            return CommandInterpretation(
                intent="error",
                server_id=None,
                service_type=None,
                action=None,
                confidence=0.0
            )
    
    def get_stats(self) -> dict:
        """Get client statistics."""
        now = datetime.now()
        minute_ago = now - timedelta(minutes=1)
        hour_ago = now - timedelta(hours=1)
        
        return {
            "cache_size": len(self._cache),
            "requests_last_minute": sum(1 for t in self._request_times if t > minute_ago),
            "requests_last_hour": sum(1 for t in self._request_times if t > hour_ago)
        }


_claude_client: Optional[ClaudeClient] = None


def get_claude_client() -> ClaudeClient:
    """Get Claude client singleton instance."""
    global _claude_client
    if _claude_client is None:
        _claude_client = ClaudeClient()
    return _claude_client
