"""CLI entry point for TikTok Shop MCP Server"""

import sys
from .server import main as run_server


def cli():
    """Command-line entry point for the TikTok Shop MCP server"""
    print("Starting TikTok Shop MCP Server via CLI entry point...")
    try:
        run_server()
    except KeyboardInterrupt:
        print("\nServer shut down by user.")
        sys.exit(0)
    except Exception as e:
        print(f"Server failed to start: {e}")
        sys.exit(1)
