"""``python -m engine`` == ``python -m engine.cli``."""

import sys

from .cli import main

sys.exit(main())
