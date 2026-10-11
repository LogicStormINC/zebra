"""Explicit synthetic business records in the proved scratch Host DB, not fake receipts."""

from __future__ import annotations

import json
import secrets
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from isolation import joint_preflight
from scratch_topology import docker
from support import Config, E2EError

# Executed in the pinned Host image so its real ORM schema/defaults are reused.
SEED = """
import asyncio,json,os,re,sys,time
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker,create_async_engine
from trench_core.orm.source import SourceRow
from trench_core.orm.event import EventRow
from trench_core.orm.trench_ai_user import TrenchAiUserRow
from trench_core.orm.trench_ai_user_subscription import TrenchAiUserSubscriptionRow
from trench_core.orm.trench_ai_subscription_period import TrenchAiSubscriptionPeriodRow
from trench_api.trench_ai_read_tools_contract import _event_payload
data=json.loads(sys.stdin.read(8192));scope=data['scope'];seed=data['seed_id']
assert re.fullmatch(r'zebra-progress-e2e-qa-[a-f0-9]{12}',scope)
assert re.fullmatch(r'[a-f0-9]{16}',seed)
assert os.environ['ZEBRA_CLIENT_NAMESPACE_ID']==scope
assert os.environ['DATABASE_URL'].endswith('/'+scope+'_trench')
url=os.environ['DATABASE_URL'].replace('postgresql://','postgresql+asyncpg://',1)
engine=create_async_engine(url,connect_args={'timeout':2,'command_timeout':2})
now=int(time.time()*1000)
async def seed_rows():
    async with asyncio.timeout(8):
        async with async_sessionmaker(engine)() as session,session.begin():
            user=await session.get(TrenchAiUserRow,data['user_id'])
            assert user is not None and user.status=='active'
            assert user.workspace_id==data['workspace_id']
            sources=[];events=[]
            for source_index in range(2):
                source_id=seed+f'{source_index:016x}'
                subscription_id='qa-sub-'+source_id
                name=f'QA {seed} source {source_index+1}'
                session.add(SourceRow(source_id=source_id,source_name=name,source_platform='rss',
                    source_type='custom_subscription',fetch_mode='manual',owner=user.user_id,
                    created_at=now,updated_at=now))
                session.add(TrenchAiUserSubscriptionRow(subscription_id=subscription_id,
                    user_id=user.user_id,workspace_id=user.workspace_id,source_id=source_id,
                    status='active',created_at=now,updated_at=now))
                session.add(TrenchAiSubscriptionPeriodRow(period_id='qa-period-'+source_id,
                    subscription_id=subscription_id,user_id=user.user_id,
                    workspace_id=user.workspace_id,source_id=source_id,
                    started_at=now-60000,ended_at=None,created_at=now-60000))
                sources.append(source_id)
                for i in range(24):
                    event_id=seed+f'{source_index*24+i+2:016x}'
                    rate=12 if source_index==0 else 8
                    summary=f'公司季度增长为{rate}%，来源{source_index+1}的独立记录。'
                    session.add(EventRow(event_id=event_id,source_id=source_id,
                        source_platform='rss',source_type='custom_subscription',source_name=name,
                        title=f'QA {seed} 记录{i:02d} 来源{source_index+1}',
                        summary=summary,content_text=summary+' 原始正文保留，不合并冲突结论。',
                        original_url='https://example.com/qa/'+event_id,
                        publish_at=now-i*1000-source_index,visible_at=now-i*1000-source_index,
                        ingest_at=now,normalized_at=now,content_hash=event_id[-16:]))
                    events.append(event_id)
            await session.flush()
            selected=select(EventRow).where(EventRow.event_id.in_(events))
            rows=(await session.scalars(selected)).all()
            assert len(rows)==48
            for row in rows:
                _event_payload(row)  # Validate the real read-tool contract before COMMIT.
        print(json.dumps({'source_ids':sources,'event_ids':events,'event_count':48,
            'per_source_count':24,'seed_id':seed,'scope':'actual_scratch_business_rows',
            'provider_or_receipt_injection':False}))
    await engine.dispose()
asyncio.run(seed_rows())
"""


def validate_seed(value: Mapping[str, Any]) -> None:
    if (
        value.get("scope") != "actual_scratch_business_rows"
        or value.get("provider_or_receipt_injection") is not False
        or value.get("event_count") != 48
        or value.get("per_source_count") != 24
        or len(set(value.get("source_ids", []))) != 2
        or len(set(value.get("event_ids", []))) != 48
    ):
        raise E2EError("scratch_business_seed_unproven")


def seed_business(config: Config) -> dict[str, Any]:
    proof = joint_preflight(
        config
    )  # Every native write is preceded by topology/DB/principal proof.
    manifest = json.loads(Path(config.isolation_manifest).read_text())
    payload = {
        "scope": proof["namespace_id"],
        "user_id": config.user_id,
        "workspace_id": config.workspace_id,
        "seed_id": secrets.token_hex(8),
    }
    output = docker(
        ["exec", "-i", manifest["containers"]["trench_api"]["id"], "python", "-c", SEED],
        input_text=json.dumps(payload),
        timeout=10,
    )
    if len(output) > 8192:
        raise E2EError("scratch_seed_evidence_oversized")
    result: dict[str, Any] = json.loads(output)
    validate_seed(result)
    return result
