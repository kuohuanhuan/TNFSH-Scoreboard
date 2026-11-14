"""Run the server: ``python -m app``"""

import uvicorn

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        proxy_headers=True,
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()
