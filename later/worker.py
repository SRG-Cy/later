"""Run with: python -m later.worker"""

import asyncio
import os

from dotenv import load_dotenv
from temporalio.client import Client
from temporalio.worker import Worker

from later.activities import ReminderActivities
from later.llm import extract_facts
from later.notify import notify
from later.policy import lookup_return_days
from later.store import MongoStore
from later.tracing import init_tracing
from later.workflow import TASK_QUEUE, ReminderWorkflow


async def main() -> None:
    load_dotenv()  # local dev; real env vars win
    init_tracing()
    client = await Client.connect(os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"))
    acts = ReminderActivities(MongoStore(os.environ["MONGODB_URI"]), notify, extract_facts, lookup_return_days)
    worker = Worker(client, task_queue=TASK_QUEUE, workflows=[ReminderWorkflow],
                    activities=[acts.read_item, acts.mark_failed, acts.send_reminder])
    print(f"worker polling task queue '{TASK_QUEUE}'", flush=True)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
