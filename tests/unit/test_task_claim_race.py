"""Claim-race test (spec T042, research R2). Two workers race the same ``ready`` task; the
Postgres advisory lock + conditional UPDATE must let exactly one execute it."""

import threading

from sqlalchemy import select

from src.core.db import get_session
from src.models.orchestration import ResultArtefact, Task
from src.orchestration import task_engine
from src.orchestration.enums import TaskStatus
from tests.orchestration_helpers import cleanup_run, seed_run_with_tasks


def test_two_workers_race_one_ready_task_exactly_one_runs_it():
    run_id, keys = seed_run_with_tasks(
        [{"key": "solo", "capability": "market_analysis", "assigned_agent": "market_analyst"}]
    )
    task_id = keys["solo"]
    with get_session() as session:
        session.query(Task).filter(Task.id == task_id).update({Task.status: TaskStatus.READY.value})
        session.commit()

    try:
        threads = [
            threading.Thread(target=task_engine._execute_task, args=(run_id, task_id))
            for _ in range(2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        with get_session() as session:
            task = session.get(Task, task_id)
            assert task is not None
            assert task.status == TaskStatus.COMPLETED.value
            assert task.retry_count == 0
            artefacts = session.scalars(
                select(ResultArtefact).where(ResultArtefact.task_id == task_id)
            ).all()
            assert len(artefacts) == 1, "task was executed more than once"
    finally:
        cleanup_run(run_id)
