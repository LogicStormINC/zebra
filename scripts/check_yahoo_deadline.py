"""Run in pinned SearXNG Python: timeout cancels transport, never its sibling; no network."""

import asyncio
import threading
import time

import searx.network as network
from curl_cffi.requests.exceptions import Timeout
from searx.network.network import Network

loop = asyncio.new_event_loop()
thread = threading.Thread(target=loop.run_forever, daemon=True)
thread.start()
original_get_loop = network.get_loop
network.get_loop = lambda: loop
started = threading.Event()
cancelled = threading.Event()
calls = []


class Client:
    async def request(self, *_args, **_kwargs):
        calls.append(True)
        started.set()
        try:
            await asyncio.sleep(0.3)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        raise Timeout("synthetic upstream timeout")


class NativeRetryNetwork(Network):
    async def get_client(self, **_kwargs):
        return Client()


async def sibling():
    await asyncio.sleep(0.35)
    return "sibling completed"


try:
    network.THREADLOCAL.network = NativeRetryNetwork(retries=1, retry_on_http_error=[0])
    network.set_timeout_for_thread(0.01)
    sibling_future = asyncio.run_coroutine_threadsafe(sibling(), loop)
    start = time.monotonic()
    try:
        network.request("GET", "https://search.yahoo.com/search")
    except Timeout:
        pass
    else:
        raise AssertionError("request should time out")
    assert started.is_set()
    assert cancelled.wait(0.07), "engine deadline left its HTTP future running"
    assert time.monotonic() - start < 0.5
    assert sibling_future.result(timeout=1) == "sibling completed"
    time.sleep(0.05)
    assert len(calls) == 1, "native retry ran after the search deadline"
    print("PASS: deadline cancels native retry future; sibling completes; no network")
finally:
    # Clean up even on the intentional red check against the unpatched image.
    async def drain():
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run_coroutine_threadsafe(drain(), loop).result(timeout=2)
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=2)
    loop.close()
    network.get_loop = original_get_loop
