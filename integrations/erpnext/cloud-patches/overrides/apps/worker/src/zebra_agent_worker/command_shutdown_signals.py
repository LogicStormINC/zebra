import signal


def install_shutdown_signals(loop, stop_new_work):
    signals = []
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop_new_work)
            signals.append(signum)
        except (NotImplementedError, RuntimeError, ValueError):
            pass  # Embedded test threads do not own process signals.
    return signals
