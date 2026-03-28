import threading
import asyncio
import logging
import time
from pymobiledevice3.services.dvt.dvt_secure_socket_proxy import DvtSecureSocketProxyService
from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService
from pymobiledevice3.lockdown import create_using_usbmux

logger = logging.getLogger("GeoPort")

class LocationService:
    def __init__(self):
        self.terminate_location_thread = False
        self.location_thread = None

    def set_location(self, latitude, longitude, rsd_host, rsd_port, ios_version_major, lockdown=None):
        self.terminate_location_thread = False
        
        async def _run_location_task():
             try:
                if ios_version_major >= 17:
                    if not rsd_host or not rsd_port:
                        logger.error("RSD data missing for iOS 17+")
                        return
                    
                    async with RemoteServiceDiscoveryService((rsd_host, int(rsd_port))) as sp_rsd:
                        with DvtSecureSocketProxyService(sp_rsd) as dvt:
                            LocationSimulation(dvt).set(latitude, longitude)
                            logger.info(f"Location set to {latitude}, {longitude}")
                            await self._keep_alive()
                else:
                    if not lockdown:
                        logger.error("Lockdown client missing for iOS < 17")
                        return
                    with DvtSecureSocketProxyService(lockdown=lockdown) as dvt:
                         LocationSimulation(dvt).clear()
                         LocationSimulation(dvt).set(latitude, longitude)
                         logger.info(f"Location set to {latitude}, {longitude}")
                         await self._keep_alive()

             except Exception as e:
                 logger.error(f"Error setting location: {e}")

        self.location_thread = threading.Thread(target=lambda: asyncio.run(_run_location_task()))
        self.location_thread.start()

    def stop_location(self):
        self.terminate_location_thread = True
    
    async def _keep_alive(self):
        while not self.terminate_location_thread:
            await asyncio.sleep(0.5)
        logger.info("Location simulation ended.")
