"""Optional captcha recognition with ddddocr (``pip install ddddocr``)."""

import logging
from base64 import b64decode
from functools import cache

from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)


@cache
def _engine():
    try:
        import ddddocr
    except Exception:  # ImportError, or a broken onnxruntime install
        logger.warning("ddddocr is unavailable; users have to type captchas manually")
        return None
    try:
        return ddddocr.DdddOcr(show_ad=False)
    except TypeError:
        return ddddocr.DdddOcr()


def available() -> bool:
    return _engine() is not None


async def solve(data_url: str) -> str | None:
    """Recognise a ``data:image/...;base64,...`` captcha. Returns ``None`` when OCR is unavailable."""
    engine = _engine()
    if engine is None:
        return None
    image = b64decode(data_url.partition(",")[2] or data_url)
    text = await run_in_threadpool(engine.classification, image)
    return text.strip().lower()
