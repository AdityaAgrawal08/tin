"""One lifecycle for the two workers hosted by the switchboard process."""

from __future__ import annotations

import asyncio

from temporalio.worker import Worker


class WorkerGroup:
    def __init__(self, *workers: Worker) -> None:
        self.workers = workers

    async def run(self) -> None:
        tasks = [asyncio.create_task(worker.run()) for worker in self.workers]
        try:
            await asyncio.gather(*tasks)
        finally:
            await self.shutdown()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def shutdown(self) -> None:
        await asyncio.gather(*(worker.shutdown() for worker in self.workers))
