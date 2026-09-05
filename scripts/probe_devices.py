"""Discover Klyqa pet devices on the LAN and dump their system info and state.

Usage: .venv/bin/python scripts/probe_devices.py [--token TOKEN] [--timeout 5]
Uses the firmware development token by default (only accepted by DEV builds).
"""

from __future__ import annotations

import argparse
import asyncio
import json

import aiohttp
from zeroconf import IPVersion, ServiceStateChange, Zeroconf
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

from pyklyqa_pet import (
    DEV_ACCESS_TOKEN,
    ZEROCONF_TYPE,
    AirPurifierDevice,
    DiscoveredDevice,
    FoodyDevice,
    KlyqaError,
    WellyDevice,
    create_device,
    parse_zeroconf_properties,
)


async def discover(timeout: float) -> list[DiscoveredDevice]:  # noqa: ASYNC109
    """Browse mDNS for the given time and return supported devices."""
    # IPv4Only: the QConnex REST API is IPv4-only, and dual-stack (IPVersion.All)
    # discovery silently receives nothing on hosts with several IPv6-only VPN
    # tunnel interfaces (utunN), which is common on this Mac.
    aiozc = AsyncZeroconf(ip_version=IPVersion.V4Only)
    found: dict[str, DiscoveredDevice] = {}
    pending: list[asyncio.Task[None]] = []
    browser: AsyncServiceBrowser | None = None
    try:

        async def resolve(zc: Zeroconf, service_type: str, name: str) -> None:
            info = AsyncServiceInfo(service_type, name)
            if not await info.async_request(zc, 3000):
                return
            addresses = info.parsed_addresses()
            if not addresses:
                return
            device = parse_zeroconf_properties(addresses[0], info.port, info.properties)
            if device is not None:
                found[device.local_device_id] = device

        def on_change(
            zeroconf: Zeroconf, service_type: str, name: str, state_change: ServiceStateChange
        ) -> None:
            if state_change is ServiceStateChange.Added:
                pending.append(asyncio.ensure_future(resolve(zeroconf, service_type, name)))

        browser = AsyncServiceBrowser(aiozc.zeroconf, ZEROCONF_TYPE, handlers=[on_change])
        await asyncio.sleep(timeout)
        await asyncio.gather(*pending, return_exceptions=True)
    finally:
        for task in pending:
            task.cancel()
        if browser is not None:
            await browser.async_cancel()
        await aiozc.async_close()
    return list(found.values())


async def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", default=DEV_ACCESS_TOKEN)
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()

    devices = await discover(args.timeout)
    print(f"Found {len(devices)} supported device(s)\n")
    async with aiohttp.ClientSession() as session:
        for discovered in devices:
            print(f"== {discovered.product_id} {discovered.local_device_id} @ {discovered.host}")
            device = create_device(
                discovered.device_type, session, discovered.host, args.token, discovered.port
            )
            try:
                info = await device.get_system_info()
                print(
                    f"   firmware {info.app_version} (sdk {info.sdk_version}),"
                    f" hw {info.hw_revision}"
                )
            except KlyqaError as err:
                print(f"   system/info ERROR: {err}")
            if isinstance(device, WellyDevice | FoodyDevice | AirPurifierDevice):
                try:
                    state = await device.get_state()
                    print("   state:", json.dumps(state.raw, indent=2))
                except KlyqaError as err:
                    print(f"   device/state ERROR: {err}")
            if isinstance(device, WellyDevice | FoodyDevice):
                try:
                    settings = await device.get_settings()
                    print("   settings:", json.dumps(settings.raw, indent=2))
                except KlyqaError as err:
                    print(f"   device/settings ERROR: {err}")
            print()


if __name__ == "__main__":
    asyncio.run(main())
