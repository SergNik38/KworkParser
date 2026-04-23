from __future__ import annotations

import argparse
import logging

from .app import Application
from .config import Settings


logger = logging.getLogger(__name__)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> None:
    configure_logging()

    parser = argparse.ArgumentParser(description="Kwork project monitor")
    parser.add_argument("--once", action="store_true", help="Run a single polling iteration")
    args = parser.parse_args()

    settings = Settings.from_env()
    app = Application(settings)

    if args.once:
        processed = app.run_once()
        logger.info("Processed %s notification candidates", processed)
        return

    app.run_forever()


if __name__ == "__main__":
    main()
