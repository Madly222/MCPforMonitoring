#!/bin/bash
# MCP Server Monitor - Run Script

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

if [ ! -d "venv" ]; then
    echo "Error: Virtual environment not found"
    echo "Run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

source venv/bin/activate

if [ ! -f "secrets.yaml" ]; then
    echo "Error: secrets.yaml not found"
    echo "Run: cp secrets.example.yaml secrets.yaml"
    exit 1
fi

echo "Starting MCP Server Monitor..."
python -m src.main
