import uuid
from datetime import timedelta

import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from later.workflow import TASK_QUEUE, ReminderWorkflow, signal, workflow_id

fired: list = []


@activity.defn(name="send_reminder")
async def stub_send(item_id: str) -> None:
    fired.append((item_id, activity.info().scheduled_time))


@pytest.fixture
async def env():
    fired.clear()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(env.client, task_queue=TASK_QUEUE, workflows=[ReminderWorkflow], activities=[stub_send]):
            yield env


async def start(env, remind_in: timedelta):
    item_id = uuid.uuid4().hex
    remind_at = await env.get_current_time() + remind_in
    handle = await env.client.start_workflow(ReminderWorkflow.run, args=[item_id, remind_at.isoformat()],
                                             id=workflow_id(item_id), task_queue=TASK_QUEUE)
    return item_id, remind_at, handle


async def test_fires_once_at_remind_at(env):
    item_id, remind_at, handle = await start(env, timedelta(days=30))
    assert await handle.result() == "reminded"
    assert len(fired) == 1 and fired[0][0] == item_id and fired[0][1] >= remind_at


async def test_done_before_remind_at_never_fires(env):
    _, _, handle = await start(env, timedelta(days=30))
    await handle.signal(ReminderWorkflow.done)
    assert await handle.result() == "done" and fired == []


async def test_cancel(env):
    _, _, handle = await start(env, timedelta(days=30))
    await handle.signal(ReminderWorkflow.cancel)
    assert await handle.result() == "cancelled" and fired == []


async def test_past_remind_at_fires_immediately(env):
    _, _, handle = await start(env, timedelta(days=-2))
    assert await handle.result() == "reminded" and len(fired) == 1


async def test_signal_after_completion_does_not_raise(env):
    item_id, _, handle = await start(env, timedelta(days=30))
    await handle.signal(ReminderWorkflow.done)
    await handle.result()
    assert await signal(env.client, item_id, "done") is False


async def test_snooze_takes_absolute_time(env):
    _, remind_at, handle = await start(env, timedelta(days=1))
    new_at = remind_at + timedelta(days=5)
    await handle.signal(ReminderWorkflow.snooze, new_at.isoformat())
    assert await handle.result() == "reminded"
    assert fired[0][1] >= new_at


async def test_garbage_snooze_is_ignored(env):
    _, remind_at, handle = await start(env, timedelta(days=1))
    await handle.signal(ReminderWorkflow.snooze, "not a date")
    assert await handle.result() == "reminded" and fired[0][1] < remind_at + timedelta(days=1)


def test_retry_never_gives_up_on_the_only_push():
    from later.workflow import RETRY, SCHEDULE_TO_CLOSE
    assert RETRY.maximum_attempts == 0 and RETRY.maximum_interval == timedelta(minutes=5)
    assert SCHEDULE_TO_CLOSE == timedelta(hours=6)
