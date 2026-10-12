#!/usr/bin/env python3
"""
Classe les datasets d'un projet selon leur position dans le Flow
(sources, intermédiaires, finaux, isolés).

Usage:
    python scripts/classer_datasets.py [PROJECT_KEY]

Sans argument, la clé projet est lue dans DSS_PROJECT_KEY (.env).
"""

import os
import sys
from pathlib import Path
from pprint import pprint

from dotenv import load_dotenv

# Allow running the script directly without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from dataiku_mcp.tools.classification_dataset import (  # noqa: E402
    classer_datasets_flow,
)


def main() -> None:
    load_dotenv()
    project_key = sys.argv[1] if len(sys.argv) > 1 else os.getenv("DSS_PROJECT_KEY")

    if not project_key:
        sys.exit("Donner la clé projet en argument ou dans DSS_PROJECT_KEY (.env)")

    pprint(classer_datasets_flow(project_key))


if __name__ == "__main__":
    main()
