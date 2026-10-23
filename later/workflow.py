"""One durable workflow per item: sleep until remind_at, then send one reminder."""

import asyncio
from datetime import datetime, timedelta

from temporalio import workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError
from temporalio.service import RPCError

TASK_QUEUE = "later"
# The push is the whole product: keep retrying (capped at 5 min apart) for up to 6 hours.
RETRY = RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2.0,
                    maximum_interval=timedelta(minutes=5), maximum_attempts=0)
SCHEDULE_TO_CLOSE = timedelta(hours=6)
# Free hosted Gemma fails ~1 call in 3 and takes ~30 s: retry reading patiently, give up after 2 hours.
READ_RETRY = RetryPolicy(initial_interval=timedelta(seconds=5), backoff_coefficient=2.0,
                         maximum_interval=timedelta(minutes=2), maximum_attempts=0)
READ_DEADLINE = timedelta(hours=2)


def workflow_id(item_id: str) -> str:
    return f"item-{item_id}"


@workflow.defn
class ReminderWorkflow:
    def __init__(self) -> None:
        self._remind_at: datetime | None = None
        self._outcome: str | None = None
        self._changed = False

    @workflow.run
    async def run(self, item_id: str, remind_at_iso: str | None = None) -> str:
        if remind_at_iso is None:  # a fresh capture: read it first
            try:
                remind_at_iso = await workflow.execute_activity(
                    "read_item", item_id, start_to_close_timeout=timedelta(minutes=5),
                    schedule_to_close_timeout=READ_DEADLINE, retry_policy=READ_RETRY)
            except ActivityError:
                await workflow.execute_activity("mark_failed", item_id, start_to_close_timeout=timedelta(seconds=30),
                                                retry_policy=RETRY)
                return "failed"
            if self._outcome:  # done/cancelled while reading
                return self._outcome
            if remind_at_iso is None:
                return "needs_info"
        self._remind_at = datetime.fromisoformat(remind_at_iso)
        while True:
            self._changed = False
            wait = max(self._remind_at - workflow.now(), timedelta(0))
            try:
                await workflow.wait_condition(lambda: self._changed, timeout=wait)
            except asyncio.TimeoutError:
                await workflow.execute_activity("send_reminder", item_id,
                                                start_to_close_timeout=timedelta(seconds=30),
                                                schedule_to_close_timeout=SCHEDULE_TO_CLOSE, retry_policy=RETRY)
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
    def snooze(self, remind_at_iso: str) -> None:
        """The app computes the new time in local Irish time, so clock changes are handled there."""
        try:
            self._remind_at = datetime.fromisoformat(remind_at_iso)
        except (TypeError, ValueError):
            return
        self._changed = True


async def start_reminder(client: Client, item_id: str, remind_at: datetime | None) -> None:
    """remind_at None: read the capture first, then wait."""
    await client.start_workflow(ReminderWorkflow.run, args=[item_id, remind_at.isoformat() if remind_at else None],
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
