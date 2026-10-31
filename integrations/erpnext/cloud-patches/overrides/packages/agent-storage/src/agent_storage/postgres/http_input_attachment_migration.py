"""Dedicated ERP DB106: explicit HTTP input proofs, unchanged Worker fencing."""

from agent_storage.postgres.migration_types import Migration

HTTP_INPUT_ATTACHMENT_MIGRATION = Migration(
    version=106,
    name="http_input_attachment_admission",
    statements=(
        (
            "ALTER TABLE artifact_payload_metadata ADD COLUMN authority_kind "
            "TEXT NOT NULL DEFAULT 'worker', ADD COLUMN http_input_authority "
            "JSONB"
        ),
        (
            "ALTER TABLE artifact_payload_metadata ALTER COLUMN reservation_e"
            "poch DROP NOT NULL, ALTER COLUMN reservation_fencing_token DROP "
            "NOT NULL, ALTER COLUMN reservation_owner_instance_id DROP NOT NU"
            "LL"
        ),
        (
            "ALTER TABLE artifact_payload_metadata ADD CONSTRAINT artifact_pa"
            "yload_authority_lane CHECK (\n            (authority_kind='worker"
            "' AND reservation_epoch IS NOT NULL\n             AND reservation"
            "_fencing_token IS NOT NULL AND reservation_owner_instance_id IS "
            "NOT NULL\n             AND http_input_authority IS NULL)\n        "
            "    OR (authority_kind='http_input' AND reservation_epoch IS NUL"
            "L\n                AND reservation_fencing_token IS NULL AND rese"
            "rvation_owner_instance_id IS NULL\n                AND http_input"
            "_authority IS NOT NULL\n                AND jsonb_typeof(http_inp"
            "ut_authority)='object'\n                AND http_input_authority "
            "?& ARRAY['context','proof','task_id','binding_digest']\n         "
            "       AND lifecycle_status IN ('finalized','pruning','pruned')\n"
            "                AND event_id IS NOT NULL AND object_version IS N"
            "OT NULL AND finalized_at IS NOT NULL)\n        )"
        ),
        (
            "ALTER TABLE artifact_payload_metadata DROP CONSTRAINT artifact_p"
            "ayload_metadata_deployment_namespace_event_id_key"
        ),
        (
            "CREATE UNIQUE INDEX artifact_worker_event_once ON artifact_paylo"
            "ad_metadata(deployment_namespace,event_id) WHERE authority_kind="
            "'worker'"
        ),
    ),
)
