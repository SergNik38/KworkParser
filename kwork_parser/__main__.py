from __future__ import annotations

import argparse

from .app import Application
from .config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Kwork project monitor")
    parser.add_argument("--once", action="store_true", help="Run a single polling iteration")
    args = parser.parse_args()

    settings = Settings.from_env()
    app = Application(settings)

    if args.once:
        sent = app.run_once()
        print(f"Sent {sent} notifications")
        return

    app.run_forever()


if __name__ == "__main__":
    main()
