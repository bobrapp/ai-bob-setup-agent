"""Enable `python -m src` as the CLI entry point.

Usage:
    python -m src --doctor
    python -m src onboard --customer acme-marketing [--dry-run]
    python -m src list
    python -m src status --customer acme-marketing
"""

from .setup_agent import cli

cli()
