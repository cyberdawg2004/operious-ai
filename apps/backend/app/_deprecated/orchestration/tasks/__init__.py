"""Task layer.

A task is the smallest unit of orchestration work the runtime executes.
Contract: one `async def execute(payload, context) -> TaskResult` method.

Tasks MUST NOT:

* log traces (the runtime owns trace emission)
* persist their own execution rows (the runtime owns persistence)
* import FastAPI / app.api (orchestration is transport-agnostic)
* import workflows (workflows compose tasks, not the other way around)

Adding a new task:

1. Implement it under `app/orchestration/tasks/<name>_task.py`.
2. Set the class-level `name` attribute (the registry key).
3. Register it in `app/dependencies/orchestration.py` alongside its
   collaborators.
"""
