# Keep the qualified provider/parser; add bounded cancellation, timing and explicit routing.
ARG SEARXNG_BASE_IMAGE=docker.io/searxng/searxng@sha256:ddd642cae6eac75412938fd846ddbf440a2df029cfeae8a562b8b205f4e35e25
FROM ${SEARXNG_BASE_IMAGE}
COPY zebra_exa.py /usr/local/searxng/searx/engines/zebra_exa.py
COPY config/settings.yml /etc/searxng/settings.yml
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

# Numeric failure metadata only: preserve the exception and all transport decisions.
path = Path('/usr/local/searxng/searx/network/client.py')
source = path.read_text()
old = 'from curl_cffi import AsyncSession, CurlHttpVersion, CurlOpt'
assert source.count(old) == 1
source = source.replace(old, 'from urllib.parse import urlsplit\nfrom curl_cffi import AsyncSession, CurlHttpVersion, CurlInfo, CurlOpt')
old = '        super().__init__(**kwargs)'
assert source.count(old) == 1
source = source.replace(old, '        kwargs.setdefault("curl_infos", (*_YAHOO_TIMING_INFO, CurlInfo.HTTP_CONNECTCODE))\n' + old)
old = '\nclass AsyncClient(AsyncSession):'
assert source.count(old) == 1
source = source.replace(old, '\n_YAHOO_TIMING_INFO = (CurlInfo.NAMELOOKUP_TIME, CurlInfo.CONNECT_TIME, CurlInfo.APPCONNECT_TIME, CurlInfo.PRETRANSFER_TIME, CurlInfo.STARTTRANSFER_TIME, CurlInfo.TOTAL_TIME)\n' + old)
old = '    @property\n    def is_closed(self)'
assert source.count(old) == 1
method = """    async def request(self, method: str, url: str, **kwargs: t.Any) -> SXNG_Response:
        response = None
        failure = None
        try:
            response = await super().request(method, url, **kwargs)
            return response
        except RequestException as error:
            failure = error
            response = getattr(error, "response", None)
            raise
        finally:
            infos = getattr(response, "infos", {}) or {}
            if failure is not None or infos.get(CurlInfo.TOTAL_TIME, 0) >= 2:
                try:
                    host = urlsplit(str(url)).hostname or ""
                except ValueError:
                    host = ""
                if host == "yahoo.com" or host.endswith(".yahoo.com"):
                    timings = {key.name.lower(): round(infos[key] * 1000, 3) for key in _YAHOO_TIMING_INFO if key in infos}
                    logging.getLogger(__name__).warning(
                        "Yahoo HTTP timing kind=%s curl_code=%s status=%s connect_status=%s ms=%s",
                        "error" if failure is not None else "slow", getattr(failure, "code", None),
                        getattr(response, "status_code", None), infos.get(CurlInfo.HTTP_CONNECTCODE), timings,
                    )


"""
path.write_text(source.replace(old, method + old))
py_compile.compile(str(path), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH)

# Reuse SearXNG's per-engine proxy setting, only for an explicit Cloud operator opt-in.
path = Path('/usr/local/searxng/searx/engines/yahoo.py')
source = path.read_text()
old = 'import typing as t'
assert source.count(old) == 1
source = source.replace(old, 'import os\n' + old)
old = 'categories = ["general", "web"]'
assert source.count(old) == 1
source = source.replace(old, '# ponytail: native proxy pooling; unset keeps existing outgoing settings.\nif _operator_proxy := os.environ.get("SEARXNG_YAHOO_PROXY"):\n    proxies = _operator_proxy\n\n' + old)
path.write_text(source)
py_compile.compile(str(path), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH)

PY
