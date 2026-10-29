"""One stdin-only proof in the pinned native image; never a host Python import."""
import json
import sys
from uuid import UUID


def main():
    from agent_storage.postgres.erp_private_workspace import native_workspace_proof
    data = sys.stdin.buffer.read(16385)
    if len(data) > 16384:
        raise ValueError('bounded proof request required')
    request = json.loads(data)
    if set(request) != {'readonly_dsn', 'shared_secret', 'ca_pem', 'session_id', 'workspace_id', 'nonce'}:
        raise ValueError('invalid proof request')
    for field in ('session_id', 'workspace_id', 'nonce'):
        if str(UUID(request[field])) != request[field]:
            raise ValueError('canonical proof identifiers required')
    identity, state, expires_at = native_workspace_proof(request['readonly_dsn'], request['session_id'],
        request['workspace_id'], shared_secret=request['shared_secret'], ca_pem=request['ca_pem'])
    print(json.dumps(dict(identity=identity, state=state, expires_at=expires_at,
        **{k: request[k] for k in ('session_id', 'workspace_id', 'nonce')}), separators=(',', ':')))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # No credentials, SQL, transport messages or traceback on container logs.
        print('private_workspace_proof_refused', file=sys.stderr)
        sys.exit(1)
