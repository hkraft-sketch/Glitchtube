from __future__ import annotations

import asyncio
import logging
import shutil
import time

from app.audio import JobState
from app.config import Settings

logger = logging.getLogger(__name__)


async def periodic_cleanup(jobs: dict[str, JobState], settings: Settings) -> None:
    """Remove expired job directories and their state every 5 minutes."""
    while True:
        await asyncio.sleep(300)
        cutoff = time.time() - (settings.CLEANUP_AGE_MINUTES * 60)
        expired = [jid for jid, j in jobs.items() if j.created_at < cutoff]
        for jid in expired:
            shutil.rmtree(settings.TEMP_DIR / jid, ignore_errors=True)
            del jobs[jid]
        if expired:
            logger.info("Cleaned up %d expired jobs", len(expired))
