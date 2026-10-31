"""Run only the real projection service for 180s in QA; never start Worker claims."""

from pathlib import Path
from threading import Event

from agent_storage import cloud_composition_from_environment
from zebra_agent_config import load_settings
from zebra_agent_worker.loop import build_worker_loop_service


def main():
    cloud = cloud_composition_from_environment()
    if cloud.deployment_namespace != "erpnext-full" or "native-db" not in cloud.dsn:
        raise ValueError("QA only")
    settings = load_settings()
    service = build_worker_loop_service(
        database_path=Path(settings.database_url), settings=settings, cloud_composition=cloud
    )
    projection = service._projection_work
    if projection is None:
        raise ValueError("native projection composition missing")
    projection.start()
    print("QA native projections only; Worker claims/provider/tools disabled", flush=True)
    try:
        Event().wait(180)
    finally:
        projection.close()


if __name__ == "__main__":
    main()
