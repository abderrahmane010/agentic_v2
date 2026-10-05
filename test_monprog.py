import os
from pprint import pprint

from dotenv import load_dotenv

from dataiku_mcp.tools.classification_dataset import (
    classer_datasets_flow,
)


load_dotenv()


def main() -> None:
    project_key = os.getenv("DSS_PROJECT_KEY")

    if not project_key:
        raise ValueError(
            "DSS_PROJECT_KEY est absente du fichier .env"
        )

    resultat = classer_datasets_flow(project_key)

    pprint(resultat)


if __name__ == "__main__":
    main()