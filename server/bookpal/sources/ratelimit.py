"""Een token bucket, zodat we een bron nooit overvragen.

MangaDex staat ongeveer 5 verzoeken per seconde per IP toe en is strenger op
``/at-home/server/`` (aandachtspunt in docs/architectuur.md). Dit is geen
optimalisatie maar een fatsoensregel: een persoonlijke bibliotheek hoort geen
publieke dienst plat te leggen.
"""

from __future__ import annotations

import threading
import time


class RateLimiter:
    """Laat gemiddeld ``rate`` aanroepen per seconde door, met een kleine burst.

    Thread-safe, want de scanner en een download kunnen tegelijk lopen.
    """

    def __init__(self, rate: float, burst: int | None = None) -> None:
        if rate <= 0:
            raise ValueError("rate moet groter dan nul zijn")
        self.rate = rate
        self.capacity = float(burst if burst is not None else max(1, int(rate)))
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Wacht tot er ruimte is voor één verzoek."""
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    self.capacity, self._tokens + (now - self._updated) * self.rate
                )
                self._updated = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                # Hoe lang duurt het tot er één token bij is?
                wait = (1.0 - self._tokens) / self.rate
            time.sleep(wait)
