# Local Home Assistant dev instance

    docker compose -f docker/docker-compose.yml up -d --build
    docker compose -f docker/docker-compose.yml logs -f homeassistant

Open http://localhost:8123, complete onboarding once (data is persisted in docker/config).
Add the integration via Settings > Devices & services > Add integration > "Klyqa Pet".

After changing integration code: restart the container
(`docker compose -f docker/docker-compose.yml restart homeassistant`).

If `network_mode: host` is not available, replace it with `ports: ["8123:8123"]`;
mDNS discovery will then not work inside the container — use the "Add device manually"
option of the integration and verify discovery with `scripts/probe_devices.py` on the host.

## Known limitation: host networking on this machine

On this development machine (Docker Desktop 29.2.1 for macOS, "Enable host networking"
not turned on in Settings > Resources > Network), `network_mode: host` starts the
container without error, but the host-networking mode only joins Docker Desktop's
internal Linux VM network — `http://localhost:8123` is not reachable from macOS itself.
`docker-compose.yml` in this repo therefore uses `ports: ["8123:8123"]` instead.

Consequence: the container cannot see LAN mDNS traffic. A manual check confirmed this:

```
docker exec ha-klyqa-pet-dev python3 -c "
import time
from zeroconf import ServiceBrowser, Zeroconf
found = []
class L:
    def add_service(self, zc, t, n): found.append(n)
    def update_service(self, zc, t, n): pass
    def remove_service(self, zc, t, n): pass
zc = Zeroconf(); ServiceBrowser(zc, '_qcxrest._tcp.local.', L()); time.sleep(6); zc.close()
print(chr(10).join(found) or 'NO SERVICES FOUND')
"
```

returned `NO SERVICES FOUND`, even though Klyqa devices (e.g.
`klyqa.welly-dev-188B0EAF2D7C._qcxrest._tcp.local.`) are announcing on the LAN.

Use the integration's "Add device manually" option for in-container testing (see
Task 13), and verify LAN discovery independently on the host with
`scripts/probe_devices.py`. If Docker Desktop's host-networking beta feature is
enabled later, switch `docker-compose.yml` back to `network_mode: host` to restore
in-container mDNS discovery.
