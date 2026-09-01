"""uvicorn entrypoint.

Run via ``uv run flightsite-serve`` (the console script defined in
``pyproject.toml``) or ``python -m flightsite``.
"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("FLIGHTSITE_HOST", "0.0.0.0")
    port = int(os.environ.get("FLIGHTSITE_PORT", "8000"))
    # log_config=None: skip uvicorn's own logging.config setup so its loggers
    # propagate to the root logger, which create_app() configures for JSON
    # structured output. Otherwise uvicorn's access/error logs would remain
    # plain text, defeating the "structured JSON logging" requirement.
    uvicorn.run(
        "flightsite.app:create_app",
        host=host,
        port=port,
        factory=True,
        log_config=None,
    )


if __name__ == "__main__":
    main()
