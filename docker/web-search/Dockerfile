# Keep the qualified provider/parser version; patch only timeout ownership.
ARG SEARXNG_BASE_IMAGE=docker.io/searxng/searxng@sha256:ddd642cae6eac75412938fd846ddbf440a2df029cfeae8a562b8b205f4e35e25
FROM ${SEARXNG_BASE_IMAGE}
RUN /usr/local/searxng/.venv/bin/python - <<'PY'
from pathlib import Path
import py_compile

path = Path('/usr/local/searxng/searx/network/__init__.py')
source = path.read_text()
old = "        except concurrent.futures.TimeoutError as e:\n            raise Timeout('Timeout') from e\n"
assert source.count(old) == 1, 'Review upstream timeout ownership before rebuilding'
# ponytail: cancel only this Future; native loop/client owns socket cleanup.
path.write_text(source.replace(old, old.replace('            raise', '            future.cancel()\n            raise')))
# The base ships unchecked-hash bytecode; refresh it so the edit actually executes.
py_compile.compile(str(path), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH)
PY
