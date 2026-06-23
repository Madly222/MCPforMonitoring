#!/usr/bin/env python3
"""Test Claude API directly."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config import get_config
from src.core.claude_client import get_claude_client

async def main():
    config = get_config()
    servers = [s.id for s in config.get_enabled_servers()]
    
    print(f"Available servers: {servers}")
    
    claude = get_claude_client()
    
    # Test command
    command = "check status of dhcp-primary"
    print(f"\nCommand: {command}")
    print("-" * 50)
    
    # Call Claude directly and print raw response
    from anthropic import Anthropic
    
    secrets = config.load_secrets()
    client = Anthropic(api_key=secrets.claude.api_key)
    
    system_prompt = claude.SYSTEM_PROMPT_COMMAND.format(servers=", ".join(servers))
    
    response = client.messages.create(
        model=secrets.claude.model,
        max_tokens=512,
        system=system_prompt,
        messages=[{"role": "user", "content": command}]
    )
    
    print(f"Raw response:")
    print(response.content[0].text)
    print("-" * 50)
    
    # Now test interpretation
    result = await claude.interpret_command(command, servers)
    print(f"\nParsed result:")
    print(f"  intent: {result.intent}")
    print(f"  server_id: {result.server_id}")
    print(f"  service_type: {result.service_type}")
    print(f"  confidence: {result.confidence}")

if __name__ == "__main__":
    asyncio.run(main())
