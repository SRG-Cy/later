"""Run with: python -m later.worker"""

import asyncio
import os

from temporalio.client import Client
from temporalio.worker import Worker

from later.activities import ReminderActivities
from later.notify import notify
from later.store import MongoStore
from later.tracing import init_tracing
from later.workflow import TASK_QUEUE, ReminderWorkflow


async def main() -> None:
    init_tracing()
    client = await Client.connect(os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"))
    acts = ReminderActivities(MongoStore(os.environ["MONGODB_URI"]), notify)
    worker = Worker(client, task_queue=TASK_QUEUE, workflows=[ReminderWorkflow], activities=[acts.send_reminder])
    print(f"worker polling task queue '{TASK_QUEUE}'", flush=True)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
