import asyncio
import sys
import threading

_loop: asyncio.AbstractEventLoop | None = None
_lock = threading.Lock()


def laco() -> asyncio.AbstractEventLoop:
    """Cria (uma vez) e devolve o laço de fundo, Proactor no Windows."""
    global _loop
    with _lock:
        if _loop is None:
            _loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
            threading.Thread(target=_loop.run_forever, daemon=True, name="assistente-loop").start()
    return _loop


def executar(coro, timeout: float = 900):
    """Roda uma corrotina no laço de fundo e espera o resultado."""
    return asyncio.run_coroutine_threadsafe(coro, laco()).result(timeout)
