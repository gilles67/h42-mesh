"""IPv6 → IPv4 fallback of the side that initiates (b): a pure state machine.

The peer endpoints are tried in order of preference (IPv6 first):

- after a switch, the family is *established* when a handshake happens;
- without handshake ``fallback_delay`` seconds after the switch, the next
  endpoint is tried (IPv6 → IPv4; IPv4 failing too → IPv6 again);
- on a less preferred endpoint, the preferred one is tried again every
  ``ipv6_retry`` seconds, even if the current one works;
- an established family whose last handshake is older than
  ``ESTABLISHED_WITHIN`` is no longer established: the same rules apply.

The backend forces a new handshake at each switch (the peer is removed then
added again), otherwise the session in progress would continue on the new
endpoint without any handshake to observe.
"""

import math
from dataclasses import dataclass

from h42mesh.agent.tunnels.backend import PeerEndpoint

# WireGuard renews its keys every 120 s while there is traffic (keepalive
# every 25 s on b): older than 180 s, the session is gone.
ESTABLISHED_WITHIN = 180.0


@dataclass
class Fallback:
    endpoints: tuple[PeerEndpoint, ...]
    fallback_delay: float
    ipv6_retry: float
    current: int = 0
    since: float = 0.0  # time of the last switch (UNIX time, as handshakes)

    def start(self, now: float) -> PeerEndpoint:
        """Begin with the preferred endpoint."""
        self.current, self.since = 0, now
        return self.endpoints[0]

    @property
    def endpoint(self) -> PeerEndpoint:
        return self.endpoints[self.current]

    def established(self, now: float, last_handshake: float | None) -> bool:
        return (
            last_handshake is not None
            and last_handshake >= math.floor(self.since)  # wg gives whole seconds
            and now - last_handshake <= ESTABLISHED_WITHIN
        )

    def step(self, now: float, last_handshake: float | None) -> PeerEndpoint | None:
        """The endpoint to switch to now, or None to keep the current one."""
        if len(self.endpoints) < 2:
            return None
        elapsed = now - self.since
        if self.established(now, last_handshake):
            if self.current != 0 and elapsed >= self.ipv6_retry:
                return self._switch(0, now)
            return None
        if elapsed >= self.fallback_delay:
            return self._switch((self.current + 1) % len(self.endpoints), now)
        return None

    def _switch(self, index: int, now: float) -> PeerEndpoint:
        self.current, self.since = index, now
        return self.endpoints[index]
