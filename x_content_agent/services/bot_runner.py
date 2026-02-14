"""Cloud Run wrapper for the Telegram bot.

Runs the bot polling loop in a background thread while serving a /health
endpoint on PORT (default 8080) so Cloud Run can verify liveness.

Usage:
    python -m x_content_agent.services.bot_runner
"""

from __future__ import annotations

import logging
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

logger = logging.getLogger(__name__)


class _HealthHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler that responds 200 on /health and GET /."""

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"healthy"}')

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        # Silence per-request logs to avoid noise
        pass


def _run_health_server(port: int) -> None:
    """Start a blocking HTTP server for Cloud Run health checks."""
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    logger.info("Health server listening on :%d", port)
    server.serve_forever()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    port = int(os.getenv("PORT", "8080"))

    # Start health server in a daemon thread
    health_thread = threading.Thread(target=_run_health_server, args=(port,), daemon=True)
    health_thread.start()
    logger.info("Health check thread started on port %d", port)

    # Import and run the bot (blocking — runs polling loop)
    from .telegram_bot import main as bot_main

    bot_main()


if __name__ == "__main__":
    main()
