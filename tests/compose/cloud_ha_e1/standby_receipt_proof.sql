-- Apply only to the disposable E1 replication pair before pausing replay.
-- The operator provisions e1_receipt_reader LOGIN with a private credential.
\set ON_ERROR_STOP on
BEGIN;

CREATE ROLE e1_receipt_owner NOLOGIN;
GRANT SELECT (deployment_namespace, action, idempotency_key, request_hash,
              status_code, response_body)
    ON public.control_plane_idempotency_records TO e1_receipt_owner;
GRANT EXECUTE ON FUNCTION pg_catalog.pg_control_system() TO e1_receipt_owner;

CREATE FUNCTION public.e1_confirm_receipt(
    expected_system text, scope text, receipt_action text, receipt_key text,
    digest text, code integer, body jsonb
)
RETURNS boolean
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog
AS $$
    SELECT pg_is_in_recovery()
       AND (SELECT system_identifier::text FROM pg_control_system()) = expected_system
       AND EXISTS (
           SELECT 1 FROM public.control_plane_idempotency_records
           WHERE deployment_namespace = scope AND action = receipt_action
             AND idempotency_key = receipt_key AND request_hash = digest
             AND status_code = code AND response_body = body
       )
$$;

ALTER FUNCTION public.e1_confirm_receipt(text, text, text, text, text, integer, jsonb)
    OWNER TO e1_receipt_owner;
REVOKE ALL ON FUNCTION public.e1_confirm_receipt(text, text, text, text, text, integer, jsonb)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.e1_confirm_receipt(text, text, text, text, text, integer, jsonb)
    TO e1_receipt_reader;

COMMIT;
