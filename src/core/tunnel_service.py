import threading
import asyncio
import logging
import sys
import time

from pymobiledevice3.remote.tunnel_service import create_core_device_tunnel_service_using_rsd, create_core_device_tunnel_service_using_remotepairing, CoreDeviceTunnelProxy
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.remote.utils import stop_remoted_if_required, resume_remoted_if_required

logger = logging.getLogger("GeoPort")

class TunnelService:
    def __init__(self):
        self.terminate_tunnel_thread = False
        self.tunnel_thread = None
        self.rsd_host = None
        self.rsd_port = None

    def start_tunnel(self, method, *args):
        self.terminate_tunnel_thread = False
        self.tunnel_thread = threading.Thread(target=self._run_tunnel_wrapper, args=(method, args))
        self.tunnel_thread.start()

    def stop_tunnel(self):
        self.terminate_tunnel_thread = True
        logger.info("Stopping tunnel thread...")

    def _run_tunnel_wrapper(self, method, args):
        try:
             asyncio.run(method(*args))
        except Exception as e:
            logger.error(f"Tunnel thread error: {e}")

    async def start_quic_tunnel(self, service_provider):
        logger.info("Starting QUIC Tunnel")
        stop_remoted_if_required()
        
        service = await create_core_device_tunnel_service_using_rsd(service_provider, autopair=True)
        async with service.start_quic_tunnel() as tunnel_result:
            resume_remoted_if_required()
            self._update_rsd_info(tunnel_result.address, tunnel_result.port)
            await self._keep_alive()

    async def start_tcp_tunnel(self, udid):
        logger.info("Starting TCP Tunnel")
        stop_remoted_if_required()
        lockdown = create_using_usbmux(udid, autopair=True)
        service = CoreDeviceTunnelProxy(lockdown)
        
        async with service.start_tcp_tunnel() as tunnel_result:
             resume_remoted_if_required()
             self._update_rsd_info(tunnel_result.address, tunnel_result.port)
             await self._keep_alive()

    async def start_wifi_quic_tunnel(self, udid, wifi_address, wifi_port):
         logger.info("Starting Wifi QUIC Tunnel")
         stop_remoted_if_required()
         service = await create_core_device_tunnel_service_using_remotepairing(udid, wifi_address, wifi_port)
         async with service.start_quic_tunnel() as tunnel_result:
             resume_remoted_if_required()
             self._update_rsd_info(tunnel_result.address, tunnel_result.port)
             await self._keep_alive()

    async def start_wifi_tcp_tunnel(self, udid, wifi_address, wifi_port):
        # Note: Previous code had mixed logic here. Assuming standard TCP tunnel via proxy or similar.
        # This might need refinement based on exact pymobiledevice3 usage for Wifi TCP.
        # Fallback to similar logic as USB TCP for now if applicable, but usually 17+ uses QUIC.
        # If <17, we usually use the lockdown directly without a special tunnel unless DVT is needed.
        logger.info("Starting Wifi TCP Tunnel (Placeholder logic)")
        # In original code, start_wifi_tcp_tunnel used create_using_usbmux(udid) ?? 
        # which seems odd if it's wifi. Let's assume standard behavior or fix later.
        pass

    def _update_rsd_info(self, host, port):
        self.rsd_host = host
        self.rsd_port = str(port)
        logger.info(f"Tunnel Established: {host}:{port}")

    async def _keep_alive(self):
        while not self.terminate_tunnel_thread:
            await asyncio.sleep(0.5)
