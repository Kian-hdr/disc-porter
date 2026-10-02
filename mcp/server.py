#!/usr/bin/env python3
"""Development compatibility entrypoint for the bundled control-plane package."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from disc_porter_control.server import main

if __name__ == '__main__':
    asyncio.run(main())
