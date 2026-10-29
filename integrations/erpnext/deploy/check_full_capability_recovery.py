"""Recover one owned QA Session under a real lease; never execute its Run."""
from datetime import UTC,datetime
import json
from pathlib import Path
from uuid import UUID
from agent_core.domain.identifiers import SessionId
from agent_storage import cloud_composition_from_environment
from zebra_agent_config import load_settings
from zebra_agent_worker.loop import build_worker_loop_service


def main():
    cloud=cloud_composition_from_environment()
    if cloud.deployment_namespace!='erpnext-full' or 'native-db' not in cloud.dsn:raise ValueError('QA only')
    settings=load_settings()
    loop=build_worker_loop_service(database_path=Path(settings.database_url),settings=settings,cloud_composition=cloud)
    claim=loop._execution_service._claim_service
    session=SessionId(UUID('c51daa77-aa7a-43ab-ae5c-273a6543472c'))
    recovered=claim.claim_session(session,worker_id='qa-projection-recovery-only',claimed_at=datetime.now(UTC),lease_ttl_seconds=30)
    try:
        print(json.dumps(dict(stage='qa_actual_fenced_projection_recovery',session=str(session),
            sequence=recovered.recovery.last_sequence,model_calls=0,search_calls=0,run_executed=False)))
    finally:claim.release_lease(recovered.lease)


if __name__=='__main__':main()
