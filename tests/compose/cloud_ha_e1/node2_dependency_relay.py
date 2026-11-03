import asyncio
import contextlib


async def pipe(source, target):
    while data := await source.read(65536):
        target.write(data)
        await target.drain()
    if target.can_write_eof():
        target.write_eof()

async def relay(port, reader, writer):
    other = None
    try:
        remote, other = await asyncio.wait_for(asyncio.open_connection("192.168.139.232", port), 3)
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(pipe(reader, other))
            tasks.create_task(pipe(remote, writer))
    except (OSError, TimeoutError, ExceptionGroup):
        pass
    finally:
        for connection in (writer, other):
            if connection is not None:
                connection.close()
                with contextlib.suppress(OSError):
                    await connection.wait_closed()

async def main():
    servers = []
    for port in (25432, 26379, 29000, 25672, 28444, 28082):
        servers.append(await asyncio.start_server(
            lambda reader, writer, port=port: relay(port, reader, writer), "127.0.0.1", port
        ))
    await asyncio.gather(*(server.serve_forever() for server in servers))

asyncio.run(main())
