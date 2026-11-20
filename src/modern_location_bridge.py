"""Keep an iOS 17+ DVT location session alive using a recent pymobiledevice3.

This file runs in a separate Python environment from the legacy GeoPort app.
The parent keeps stdin open and writes one newline to clear the location.
"""

import argparse
import asyncio
import json
import math
import sys
from pathlib import Path

from pymobiledevice3 import common

common._HOMEFOLDER = Path.home() / ".geoport" / "pmd3-data"

from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.remote.rsd_tunnel import PreferredRsdTunnel
from pymobiledevice3.services.cryptexd import CryptexdService
from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
from pymobiledevice3.usbmux import select_device


async def verify_target(udid):
    device = await select_device(udid=udid)
    if device is None:
        raise RuntimeError(f"Device {udid} is not connected")
    if device.connection_type != "USB":
        raise RuntimeError(f"Device {udid} must be connected by USB")
    lockdown = await create_using_usbmux(
        device.serial, connection_type=device.connection_type, autopair=False
    )
    try:
        version = lockdown.product_version
        if not version.startswith("27."):
            raise RuntimeError(f"Expected iOS 27, but {udid} reports {version}")
        if not await lockdown.get_developer_mode_status():
            raise RuntimeError("Developer Mode is disabled")
    finally:
        await lockdown.close()


async def run(args):
    await verify_target(args.udid)
    async with PreferredRsdTunnel(serial=args.udid) as rsd:
        cryptex = CryptexdService(rsd)
        installed = await cryptex.copy_installed()
        if not any(item.identifier == "com.apple.MobileAsset.DDI" for item in installed):
            await cryptex.auto_install_ddi()
        async with DvtProvider(rsd) as dvt, LocationSimulation(dvt) as simulator:
            if args.action == "clear":
                await simulator.clear()
                print(json.dumps({"cleared": True}), flush=True)
                return
            if not math.isfinite(args.latitude) or not math.isfinite(args.longitude):
                raise ValueError("Coordinates must be finite numbers")
            if not (-90 <= args.latitude <= 90 and -180 <= args.longitude <= 180):
                raise ValueError("Coordinates are out of range")
            await simulator.set(args.latitude, args.longitude)
            print(json.dumps({"ready": True}), flush=True)
            try:
                await asyncio.to_thread(sys.stdin.readline)
            finally:
                await simulator.clear()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("set", "clear"))
    parser.add_argument("--udid", required=True)
    parser.add_argument("latitude", type=float, nargs="?")
    parser.add_argument("longitude", type=float, nargs="?")
    args = parser.parse_args()
    if args.action == "set" and (args.latitude is None or args.longitude is None):
        parser.error("set requires latitude and longitude")
    try:
        asyncio.run(run(args))
    except Exception as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}), flush=True)
        sys.exit(1)
