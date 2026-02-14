"""Main entry point for the X Content Agent system.

Can be invoked as:
- CLI: python -m x_content_agent.main
- Cloud Run: receives HTTP trigger from Cloud Scheduler
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env files before anything else touches google libs
_root = Path(__file__).parent.parent
load_dotenv(_root / ".env.local")  # secrets (local dev only, ignored in prod)
load_dotenv(_root / ".env")        # non-secret config

from .shared.utils import setup_logging

logger = logging.getLogger(__name__)


async def run_pipeline() -> dict:
    """Run the content pipeline and return results."""
    # Import here to avoid circular imports and allow lazy init
    from .pipeline import ContentPipeline

    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    pipeline = ContentPipeline(project_id=project_id)
    result = await pipeline.run()
    return result.model_dump(mode="json")


def create_cloud_run_app():
    """Create a FastAPI app for Cloud Run that handles scheduler triggers."""
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

    app = FastAPI(title="X Content Agent Pipeline")

    @app.post("/run")
    async def trigger_pipeline(request: Request):
        """Endpoint triggered by Cloud Scheduler to run the daily pipeline."""
        logger.info("Pipeline triggered via HTTP")
        try:
            result = await run_pipeline()
            return JSONResponse(content=result)
        except Exception as e:
            logger.error("Pipeline failed: %s", e, exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"error": str(e)},
            )

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    return app


# Cloud Run entry point
app = create_cloud_run_app()


if __name__ == "__main__":
    setup_logging(os.getenv("LOG_LEVEL", "INFO"))
    logger.info("Starting X Content Agent pipeline (CLI mode)")
    result = asyncio.run(run_pipeline())
    print(f"Pipeline completed: {result}")
    sys.exit(0 if not result.get("errors") else 1)
