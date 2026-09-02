"""Make `python -m app` run the FastAPI server with uvicorn."""
import uvicorn

from app.core.config import settings


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.ENVIRONMENT == "local",
        log_level=settings.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    main()
