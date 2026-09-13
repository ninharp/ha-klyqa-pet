"""Try a Klyqa cloud login against each environment and list the account's devices.

Usage:
  KLYQA_EMAIL=you@example.com KLYQA_PASSWORD=secret \\
    .venv/bin/python scripts/probe_cloud.py [--environment-name Klyqapet]

Credentials are read from the environment so they never end up in the shell
history or in an argument list. Useful when a device was onboarded with a
different app build and it is unclear which cloud environment holds it: the
script reports, per environment, whether login succeeded and which devices the
account exposes.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import aiohttp

from pyklyqa_pet import Environment, KlyqaAuthError, KlyqaCloudClient, KlyqaError
from pyklyqa_pet.const import CLOUD_BASE_URLS, CLOUD_ENVIRONMENT_NAME


async def probe(email: str, password: str, environment_name: str) -> None:
    """Log in to every known environment and print the devices found."""
    async with aiohttp.ClientSession() as session:
        for environment in Environment:
            base_url = CLOUD_BASE_URLS[environment]
            print(f"\n=== {environment.value} ({base_url}) ===")
            client = KlyqaCloudClient(session, environment)
            try:
                await client.login(email, password, environment_name=environment_name)
            except KlyqaAuthError as err:
                print(f"  login rejected: {err}")
                continue
            except KlyqaError as err:
                print(f"  unreachable: {err}")
                continue
            print("  login ok")
            try:
                devices = await client.list_devices()
            except KlyqaError as err:
                print(f"  listing devices failed: {err}")
                continue
            if not devices:
                print("  no devices on this account")
            for device in devices:
                print(f"  {device.local_device_id}  {device.product_id:32} {device.name}")


def main() -> int:
    """Parse arguments, read credentials from the environment and run the probe."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--environment-name",
        default=CLOUD_ENVIRONMENT_NAME,
        help="value sent as environmentName in the login payload",
    )
    args = parser.parse_args()

    email = os.environ.get("KLYQA_EMAIL")
    password = os.environ.get("KLYQA_PASSWORD")
    if not email or not password:
        print("Set KLYQA_EMAIL and KLYQA_PASSWORD in the environment.", file=sys.stderr)
        return 2

    asyncio.run(probe(email, password, args.environment_name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
