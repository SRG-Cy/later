"""One durable workflow per item: sleep until remind_at, then send one reminder."""

import asyncio
from datetime import datetime, timedelta

from temporalio import workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.service import RPCError

TASK_QUEUE = "later"
RETRY = RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2.0, maximum_attempts=5)


def workflow_id(item_id: str) -> str:
    return f"item-{item_id}"


@workflow.defn
class ReminderWorkflow:
    def __init__(self) -> None:
        self._remind_at: datetime | None = None
        self._outcome: str | None = None
        self._changed = False

    @workflow.run
    async def run(self, item_id: str, remind_at_iso: str) -> str:
        self._remind_at = datetime.fromisoformat(remind_at_iso)
        while True:
            self._changed = False
            wait = max(self._remind_at - workflow.now(), timedelta(0))
            try:
                await workflow.wait_condition(lambda: self._changed, timeout=wait)
            except asyncio.TimeoutError:
                await workflow.execute_activity("send_reminder", item_id,
                                                start_to_close_timeout=timedelta(seconds=30), retry_policy=RETRY)
                return "reminded"
            if self._outcome:
                return self._outcome

    @workflow.signal
    def done(self) -> None:
        self._outcome, self._changed = "done", True

    @workflow.signal
    def cancel(self) -> None:
        self._outcome, self._changed = "cancelled", True

    @workflow.signal
    def snooze(self, days: int) -> None:
        self._remind_at += timedelta(days=days)
        self._changed = True


async def start_reminder(client: Client, item_id: str, remind_at: datetime) -> None:
    await client.start_workflow(ReminderWorkflow.run, args=[item_id, remind_at.isoformat()],
                                id=workflow_id(item_id), task_queue=TASK_QUEUE)


async def signal(client: Client, item_id: str, name: str, arg=None) -> bool:
    """Signal a waiting reminder. Returns False if it already finished (e.g. Done tapped after the push)."""
    handle = client.get_workflow_handle(workflow_id(item_id))
    try:
        if arg is None:
            await handle.signal(name)
        else:
            await handle.signal(name, arg)
    except RPCError:
        return False
    return True
