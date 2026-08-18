"""PostgreSQL v10 schema for governed Memory authority."""

from agent_storage.postgres.migration_types import Migration

GOVERNED_MEMORY_MIGRATION = Migration(
    version=10,
    name="governed_memory_authority",
    statements=(
        """
        CREATE TABLE governed_memory_scan_snapshots (
            deployment_namespace TEXT NOT NULL,
            snapshot_id UUID NOT NULL,
            operation_id TEXT NOT NULL,
            operator TEXT NOT NULL,
            reason TEXT NOT NULL,
            scope_digest TEXT NOT NULL CHECK (scope_digest ~ '^[0-9a-f]{64}$'),
            query_json JSONB NOT NULL CHECK (jsonb_typeof(query_json) = 'object'),
            created_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            expires_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (deployment_namespace, snapshot_id),
            UNIQUE (deployment_namespace, operation_id),
            CHECK (operation_id = btrim(operation_id) AND operation_id != ''),
            CHECK (operator = btrim(operator) AND operator != ''),
            CHECK (reason = btrim(reason) AND reason != ''),
            CHECK (expires_at > created_at)
        )
        """,
        """
        CREATE TABLE governed_memory_records (
            deployment_namespace TEXT NOT NULL,
            memory_id UUID NOT NULL,
            revision BIGINT NOT NULL CHECK (revision >= 1),
            memory_type TEXT NOT NULL CHECK (memory_type IN (
                'preference', 'project_rule', 'procedure', 'episodic',
                'failed_attempt', 'architecture_fact'
            )),
            text TEXT,
            confidence DOUBLE PRECISION NOT NULL CHECK (confidence BETWEEN 0 AND 1),
            status TEXT NOT NULL CHECK (status IN (
                'candidate', 'confirmed', 'superseded', 'expired', 'deleted'
            )),
            visibility TEXT NOT NULL CHECK (visibility IN ('repo', 'user', 'tenant')),
            tenant_id TEXT, user_id TEXT, repo_id TEXT,
            source_session_id UUID,
            source_event_start BIGINT CHECK (source_event_start >= 0),
            source_event_end BIGINT CHECK (source_event_end >= 0),
            source_commit_sha TEXT,
            superseded_by UUID,
            expires_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            creation_key TEXT NOT NULL CHECK (creation_key ~ '^[0-9a-f]{64}$'),
            content_digest TEXT NOT NULL CHECK (content_digest ~ '^[0-9a-f]{64}$'),
            provenance_digest TEXT NOT NULL CHECK (provenance_digest ~ '^[0-9a-f]{64}$'),
            search_vector TSVECTOR GENERATED ALWAYS AS (
                to_tsvector('simple', coalesce(text, ''))
            ) STORED,
            PRIMARY KEY (deployment_namespace, memory_id),
            UNIQUE (deployment_namespace, creation_key),
            FOREIGN KEY (deployment_namespace, source_session_id)
                REFERENCES session_streams (deployment_namespace, session_id),
            FOREIGN KEY (
                deployment_namespace, source_session_id, source_event_start
            ) REFERENCES session_events (deployment_namespace, session_id, sequence),
            FOREIGN KEY (
                deployment_namespace, source_session_id, source_event_end
            ) REFERENCES session_events (deployment_namespace, session_id, sequence),
            FOREIGN KEY (deployment_namespace, superseded_by)
                REFERENCES governed_memory_records (deployment_namespace, memory_id)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK ((source_event_start IS NULL) = (source_event_end IS NULL)),
            CHECK (source_event_start IS NULL OR source_session_id IS NOT NULL),
            CHECK (source_event_end IS NULL OR source_event_end >= source_event_start),
            CHECK ((status = 'superseded') = (superseded_by IS NOT NULL)),
            CHECK (superseded_by IS NULL OR superseded_by != memory_id),
            CHECK ((status = 'deleted') = (text IS NULL)),
            CHECK (text IS NULL OR (length(btrim(text)) > 0 AND text = btrim(text))),
            CHECK (created_at <= updated_at),
            CHECK (expires_at IS NULL OR expires_at >= created_at),
            CHECK (tenant_id IS NULL OR (tenant_id = btrim(tenant_id) AND tenant_id != '')),
            CHECK (user_id IS NULL OR (user_id = btrim(user_id) AND user_id != '')),
            CHECK (repo_id IS NULL OR (repo_id = btrim(repo_id) AND repo_id != '')),
            CHECK (source_commit_sha IS NULL OR (
                source_commit_sha = btrim(source_commit_sha) AND source_commit_sha != ''
            )),
            CHECK ((visibility != 'repo') OR (repo_id IS NOT NULL AND btrim(repo_id) != '')),
            CHECK ((visibility != 'user') OR (user_id IS NOT NULL AND btrim(user_id) != '')),
            CHECK ((visibility != 'tenant') OR (tenant_id IS NOT NULL AND btrim(tenant_id) != ''))
        )
        """,
        """
        CREATE INDEX governed_memory_repo_query ON governed_memory_records
        (deployment_namespace, repo_id, status, updated_at DESC, created_at DESC, memory_id)
        """,
        """
        CREATE INDEX governed_memory_user_query ON governed_memory_records
        (deployment_namespace, user_id, status, updated_at DESC, created_at DESC, memory_id)
        """,
        """
        CREATE INDEX governed_memory_tenant_query ON governed_memory_records
        (deployment_namespace, tenant_id, status, updated_at DESC, created_at DESC, memory_id)
        """,
        """
        CREATE INDEX governed_memory_source_query ON governed_memory_records
        (deployment_namespace, source_session_id, status, updated_at DESC, memory_id)
        """,
        """
        CREATE INDEX governed_memory_search ON governed_memory_records
        USING GIN (search_vector) WHERE status != 'deleted'
        """,
        """
        CREATE UNIQUE INDEX governed_memory_repo_singleton_confirmed
        ON governed_memory_records (deployment_namespace, repo_id, memory_type)
        WHERE visibility = 'repo' AND status = 'confirmed'
          AND memory_type IN ('project_rule', 'procedure', 'architecture_fact')
        """,
        """
        CREATE UNIQUE INDEX governed_memory_user_singleton_confirmed
        ON governed_memory_records (deployment_namespace, user_id, memory_type)
        WHERE visibility = 'user' AND status = 'confirmed'
          AND memory_type IN ('project_rule', 'procedure', 'architecture_fact')
        """,
        """
        CREATE UNIQUE INDEX governed_memory_tenant_singleton_confirmed
        ON governed_memory_records (deployment_namespace, tenant_id, memory_type)
        WHERE visibility = 'tenant' AND status = 'confirmed'
          AND memory_type IN ('project_rule', 'procedure', 'architecture_fact')
        """,
        """
        CREATE TABLE governed_memory_scan_items (
            deployment_namespace TEXT NOT NULL,
            snapshot_id UUID NOT NULL,
            ordinal BIGINT NOT NULL CHECK (ordinal >= 0),
            memory_id UUID NOT NULL,
            captured_revision BIGINT NOT NULL CHECK (captured_revision >= 1),
            PRIMARY KEY (deployment_namespace, snapshot_id, ordinal),
            UNIQUE (deployment_namespace, snapshot_id, memory_id),
            FOREIGN KEY (deployment_namespace, snapshot_id)
                REFERENCES governed_memory_scan_snapshots
                (deployment_namespace, snapshot_id) ON DELETE CASCADE,
            FOREIGN KEY (deployment_namespace, memory_id)
                REFERENCES governed_memory_records (deployment_namespace, memory_id)
        )
        """,
        """
        CREATE INDEX governed_memory_scan_expiry
        ON governed_memory_scan_snapshots (deployment_namespace, expires_at)
        """,
        """
        CREATE TABLE governed_memory_operations (
            deployment_namespace TEXT NOT NULL,
            operation_id TEXT NOT NULL CHECK (
                length(operation_id) BETWEEN 1 AND 255 AND operation_id = btrim(operation_id)
            ),
            operation_kind TEXT NOT NULL CHECK (
                operation_kind IN ('worker_candidates', 'administrative_review')
            ),
            request_digest TEXT NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
            status TEXT NOT NULL CHECK (status = 'committed'),
            session_id UUID NOT NULL,
            anchor_event_start BIGINT NOT NULL CHECK (anchor_event_start >= 0),
            anchor_event_end BIGINT NOT NULL CHECK (anchor_event_end >= anchor_event_start),
            anchor_start_event_id UUID NOT NULL,
            anchor_end_event_id UUID NOT NULL,
            result_schema TEXT NOT NULL CHECK (
                result_schema = 'governed-memory-operation-result/1'
            ),
            result_json JSONB NOT NULL CHECK (jsonb_typeof(result_json) = 'object'),
            result_digest TEXT NOT NULL CHECK (result_digest ~ '^[0-9a-f]{64}$'),
            committed_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp(),
            PRIMARY KEY (deployment_namespace, operation_id),
            FOREIGN KEY (
                deployment_namespace, session_id, anchor_event_start, anchor_start_event_id
            ) REFERENCES session_events (
                deployment_namespace, session_id, sequence, event_id
            ),
            FOREIGN KEY (
                deployment_namespace, session_id, anchor_event_end, anchor_end_event_id
            ) REFERENCES session_events (
                deployment_namespace, session_id, sequence, event_id
            )
        )
        """,
    ),
)
