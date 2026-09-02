"""``python -m sim`` entry point.

Equivalent to ``python -m sim.runner``; provided for users who
prefer the shorter form.
"""
from __future__ import annotations

import asyncio
import sys

from sim.runner import main


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
