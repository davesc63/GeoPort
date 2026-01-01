import asyncio
import logging
import time
import sys
from pymobiledevice3.usbmux import list_devices
from pymobiledevice3.lockdown import create_using_usbmux, create_using_tcp
from pymobiledevice3.services.amfi import AmfiService
from pymobiledevice3.exceptions import DeviceHasPasscodeSetError
try:
    from pymobiledevice3.cli.remote import cli_install_wetest_drivers
except ImportError:
    cli_install_wetest_drivers = None

from pymobiledevice3.remote.utils import get_rsds
from pymobiledevice3.remote.tunnel_service import get_remote_pairing_tunnel_services
from pymobiledevice3.pair_records import get_preferred_pair_record, get_remote_pairing_record_filename
from pymobiledevice3.common import get_home_folder
import subprocess

from config import Config

logger = logging.getLogger("GeoPort")

class DeviceManager:
    def __init__(self):
        self.device_map = {} # Store device objects
        self.rsd_data_map = {} # Store RSD data

    def list_devices(self, wifi_host=None, udid=None):
        try:
            connected_devices = {}
            all_devices = list_devices()
            logger.info(f"Raw Devices: {all_devices}")

            if wifi_host and udid:
                # Manual Wifi Connection Logic
                logger.warning(f"Wifi requested to {wifi_host} for udid: {udid}")
                try:
                    lockdown = create_using_tcp(hostname=wifi_host, identifier=udid)
                    info = lockdown.short_info
                    info['wifiState'] = lockdown.enable_wifi_connections = True
                    info['userLocale'] = None # TODO: Inject this dependency or fetch
                    info['ConnectionType'] = 'Network'
                    
                    conn_type = "Manual Wifi"
                    connected_devices[udid] = {conn_type: [info]}
                except Exception as e:
                    logger.error(f"Failed to connect to manual wifi device: {e}")

            for device in all_devices:
                udid = device.serial
                connection_type = device.connection_type
                
                try:
                    lockdown = create_using_usbmux(udid, connection_type=connection_type, autopair=True)
                    info = lockdown.short_info
                    wifi_state = lockdown.enable_wifi_connections
                    
                    if not wifi_state:
                        logger.info("Enabling Wifi Connections")
                        lockdown.enable_wifi_connections = True
                        wifi_state = True
                        
                    info['wifiState'] = wifi_state
                    info['userLocale'] = None # TODO
                    
                    if connection_type == "Network":
                        connection_type = "Wifi"

                    connected_devices.setdefault(udid, {})
                    connected_devices[udid].setdefault(connection_type, []).append(info)
                    
                except Exception as e:
                    logger.error(f"Error processing device {udid}: {e}")

            return connected_devices

        except Exception as e:
            logger.error(f"Error listing devices: {e}")
            return {'error': str(e)}

    def check_developer_mode(self, udid, connection_type):
        try:
            lockdown = create_using_usbmux(udid, connection_type=connection_type, autopair=True)
            result = lockdown.developer_mode_status
            logger.info(f"Developer Mode Check result: {result}")
            return result
        except Exception:
            return False

    def enable_developer_mode(self, udid, connection_type):
        home = get_home_folder()
        if connection_type == "Network":
            # Check pair record
            pair_record = get_preferred_pair_record(udid, home)
            if pair_record is None:
                 return False, "No Pair Record Found. Please use a USB cable first."

        try:
            lockdown = create_using_usbmux(udid, connection_type=connection_type, autopair=True)
            AmfiService(lockdown).enable_developer_mode()
            self.mount_developer_image(udid)
            return True, None
        except DeviceHasPasscodeSetError:
            return False, "Device has a passcode set. Please remove it temporarily."
        except Exception as e:
            return False, str(e)

    def mount_developer_image(self, udid, connection_type='USB'):
        # Helper wrapper for pymobiledevice3 auto_mount
        from pymobiledevice3.cli.mounter import auto_mount
        logger.info(f"Mounting developer image for {udid}")
        lockdown = create_using_usbmux(udid, autopair=True)
        auto_mount(lockdown)
    
    def get_devices_with_retry(self, timeout=Config.DEFAULT_BONJOUR_TIMEOUT, max_attempts=10):
        # Implementation of get_devices_with_retry from original main.py
        if Config.IS_WINDOWS: # simplified check
             pass # Windows driver logic handled elsewhere or assumed if needed
        
        for attempt in range(1, max_attempts + 1):
            try:
                devices = asyncio.run(get_rsds(timeout))
                if devices:
                    return devices
            except Exception as e:
                logger.warning(f"Attempt {attempt}: {e}")
            time.sleep(1)
        raise RuntimeError("No devices found after multiple attempts.")

    def get_wifi_device(self, udid, timeout=Config.DEFAULT_BONJOUR_TIMEOUT):
         # Implementation of get_wifi_with_retry logic
         for attempt in range(1, 11):
            try:
                devices = asyncio.run(get_remote_pairing_tunnel_services(timeout))
                if devices:
                    for device in devices:
                        if device.remote_identifier == udid:
                            return device
            except Exception:
                pass
            time.sleep(1)
         return None
