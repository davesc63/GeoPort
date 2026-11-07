import locale
import json
import math
import os
import re
import sys
import time
import pyuac
import psutil
import signal
import socket
import random
import asyncio
import argparse
import requests
import threading
import webbrowser
import subprocess
import pycountry
from logging.handlers import RotatingFileHandler

from flask import Flask, jsonify, make_response, render_template, request, Response
from urllib3.exceptions import InsecureRequestWarning, ConnectionError
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)
from contextlib import asynccontextmanager

from pymobiledevice3.usbmux import list_devices
from pymobiledevice3.cli.mounter import auto_mount
from pymobiledevice3.lockdown import create_using_usbmux, create_using_tcp, get_mobdev2_lockdowns
from pymobiledevice3.services.amfi import AmfiService
from pymobiledevice3.exceptions import DeviceHasPasscodeSetError, NoDeviceConnectedError
from pymobiledevice3.services.dvt.dvt_secure_socket_proxy import DvtSecureSocketProxyService
from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService
from pymobiledevice3.remote.utils import stop_remoted_if_required, resume_remoted_if_required, get_rsds
from pymobiledevice3.remote.tunnel_service import create_core_device_tunnel_service_using_rsd, get_remote_pairing_tunnel_services, start_tunnel, create_core_device_tunnel_service_using_remotepairing, get_core_device_tunnel_services, CoreDeviceTunnelProxy
#from pymobiledevice3.cli.remote import install_driver_if_required
from pymobiledevice3.osu.os_utils import get_os_utils
from pymobiledevice3.bonjour import DEFAULT_BONJOUR_TIMEOUT, browse_mobdev2
from pymobiledevice3.pair_records import get_local_pairing_record, get_remote_pairing_record_filename, get_preferred_pair_record
from pymobiledevice3.common import get_home_folder

# WeTest driver install was removed from newer pymobiledevice3 releases -
# keep the app importable on any 4.x version (issue #167).
try:
    from pymobiledevice3.cli.remote import cli_install_wetest_drivers
except ImportError:
    cli_install_wetest_drivers = None

from pymobiledevice3.cli.remote import tunnel_task
from pymobiledevice3.lockdown import LockdownClient
from pymobiledevice3.lockdown_service_provider import LockdownServiceProvider
from pymobiledevice3.remote.common import TunnelProtocol

#========= Arg Parser ========
# Parse command-line arguments
parser = argparse.ArgumentParser()
parser.add_argument('--no-browser', action='store_true', help='Skip auto opening the browser')
parser.add_argument('--port', type=int, help='Specify port number to listen on for web browser requests')
parser.add_argument('--wifihost', type=str, help='Specify the wifi IP address to connect to')
parser.add_argument('--udid', type=str, help='Specify the device udid to target')
parser.add_argument('--restart-remoted', action='store_true',
                    help="Stop/restart the Apple 'remoted' service around tunnels (macOS only). "
                         "Off by default because it can break Xcode device connections (issue #44)")
args = parser.parse_args()
#========= Arg Parser ========

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
OSUTILS = get_os_utils()


import logging


# Get or create a logger instance named "GeoPort"
# Guard: under pythonw.exe (e.g. a double-clicked .pyw) sys.stderr is None and
# a bare StreamHandler() would crash the process on the first log line.
_log_handlers = []
if sys.stderr is not None:
    _log_handlers.append(logging.StreamHandler())
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=_log_handlers
)

# Create a logger named "GeoPort"
logger = logging.getLogger("GeoPort")
logging.getLogger("urllib3").setLevel(logging.WARNING)

# Also write logs to a rotating file so "it just stopped working" reports can
# be debugged offline (issues #148/#172/#174 have no console output available).
log_file_path = os.path.join(os.getcwd(), 'GeoPort.log')
try:
    file_handler = RotatingFileHandler(log_file_path, maxBytes=2_000_000, backupCount=3)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(file_handler)
except Exception as e:
    print(f"Could not open log file: {e}")

logging.getLogger('werkzeug').disabled = True
#log.disabled = True

app = Flask(__name__)
# Always re-check template mtimes (we run without debug) so UI edits take
# effect on the next request instead of being frozen for the process lifetime.
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Define constants
# Get the home directory of the current user
home_dir = os.path.expanduser("~")
is_windows = sys.platform == 'win32'
base_directory = getattr(sys, '_MEIPASS', os.path.abspath(os.path.dirname(sys.argv[0])))
flask_port = 54321
api_url = "https://projectzerothree.info/api.php?format=json"
api_data = None
user_locale = None
location = None
rsd_data = None
rsd_host = None
rsd_port = None
rsd_data_map = {}
wifi_address = None
wifihost = args.wifihost
wifi_port = None
connection_type = None
udid = None
lockdown = None
ios_version = None
pair_record = None
error_message = None
sudo_message = ""
captured_output = None
GITHUB_REPO = 'davesc63/GeoPort'
CURRENT_VERSION_FILE = 'CURRENT_VERSION'
BROADCAST_FILE = 'BROADCAST'
# Short-lived caches so a page refresh doesn't block on external network
# calls (GitHub raw, ip-api.com, fuel API) on every single load.
_version_cache = None
_version_cache_ts = 0
_broadcast_cache = None
_broadcast_cache_ts = 0
_country_cache = None
_country_cache_ts = 0
_api_data_ts = 0
APP_VERSION_NUMBER = "2.3.3"
APP_VERSION_TYPE = "fuel"
terminate_tunnel_thread = False
terminate_location_thread = False
location_threads = []
tunnel_thread = None
location_thread = None
connect_attempt_lock = threading.Lock()
# --- Server-side route playback (GPX/route walker) ---------------------------
# Replaces the old browser-driven playback (a setTimeout per point, each of
# which POSTed /set_location and re-spawned the location thread). The server
# holds ONE RSD/DVT session open for the whole route and walks it at a
# constant speed (issue #137).
route_points = []            # list of (lat, lng)
route_speed_kmh = 5.0
route_index = -1
route_generation = 0
route_resume_start = 0
route_active = False
route_paused = False
route_finished = False
route_error = None
route_thread = None
terminate_route_thread = False
route_state_lock = threading.Lock()

# --- Optional API token for remote/headless use (set GEOPORT_TOKEN env) ----
GEOPORT_TOKEN = os.environ.get('GEOPORT_TOKEN', '')
timeout = DEFAULT_BONJOUR_TIMEOUT

# Get the current platform using sys.platform
current_platform = sys.platform

# Map the platform names to standard values
platform = {
    'win32': 'Windows',
    'linux': 'Linux',
    'darwin': 'MacOS',
}.get(current_platform, 'Unknown')

# Check if running as sudo
if current_platform == "darwin":
    if os.geteuid() != 0:
        logger.error("*********************** WARNING ***********************")
        logger.error("Not running as Sudo, this probably isn't going to work")
        logger.error("*********************** WARNING ***********************")
        sudo_message = "Not running as Sudo, this probably isn't going to work"
    else:
        logger.info("Running as Sudo")
        sudo_message = ""



def fetch_api_data(api_url):
    global api_data, _api_data_ts
    # Fuel prices don't change minute to minute - only re-fetch at most every
    # 5 minutes instead of on every page load.
    now = time.time()
    if api_data is not None and now - _api_data_ts < 300:
        return api_data
    try:
        api_data = requests.get(api_url, verify=False).json()
        _api_data_ts = now
        return api_data
    except requests.exceptions.RequestException as e:
        logger.error(f"Error: {e}")
        logger.error(f"API is unreachable or there was an error during the request")
        logger.error("Sorry - Fuel data is not available")
        return None
    except ConnectionError as e:
        logger.error("Error: Name resolution failed.")
        logger.error("Please check your internet connection or the correctness of the API URL.")
        logger.error("Sorry - Fuel data is not available")
        logger.error(f"Details: {e}")
        return None

def create_geoport_folder():
    # Define the path to the GeoPort folder
    geoport_folder = os.path.join(home_dir, 'GeoPort')

    # Check if the GeoPort folder exists, create it if not
    if not os.path.exists(geoport_folder):
        os.makedirs(geoport_folder)
        logger.info(f"GeoPort Home: {geoport_folder}")
        logger.info("GeoPort folder created successfully")

    # Set permissions for the GeoPort folder
    if current_platform == 'win32':
        # Windows permissions (read/write for everyone)
        os.system(f"icacls {geoport_folder} /grant Everyone:(OI)(CI)F")
        logger.info("Permissions set for GeoPort folder on Windows")
    else:  # Linux and MacOS
        # POSIX permissions (read/write for everyone)
        os.chmod(geoport_folder, 0o777)
        logger.info("Permissions set for GeoPort folder on MacOS")



# Define the function to be executed in the thread
def run_tunnel(service_provider):

    try:
        asyncio.run(start_quic_tunnel(service_provider))

        logger.info("run_tunnel completed")

    except Exception as e:
        # Log the error - the stale-tunnel check rebuilds the tunnel on the
        # next location request (issue #59: previously errors were swallowed).
        logger.error(f"Error in run_tunnel: {e}")

    #return

# Define a function to start the tunnel thread
def start_tunnel_thread(service_provider):
    global terminate_tunnel_thread, tunnel_thread  # Declare the global variables
    terminate_tunnel_thread = False  # Set the value of the global variable
    # Daemon thread so a wedged tunnel can never block app exit (issue #59).
    tunnel_thread = threading.Thread(target=run_tunnel, args=(service_provider,), daemon=True)
    tunnel_thread.start()
    return

async def start_quic_tunnel(service_provider: RemoteServiceDiscoveryService) -> None:

    logger.warning("Start USB QUIC tunnel")

    global terminate_tunnel_thread
    if args.restart_remoted:
        stop_remoted_if_required()
    #install_driver_if_required()

    # if sys.platform == 'win32':
    #     logger.info("Windows System - Driver Check Required")
    #     if version_check(ios_version):
    #         logger.warning("Installing WeTest Driver - QUIC Tunnel")
    #         cli_install_wetest_drivers()

    service = await create_core_device_tunnel_service_using_rsd(service_provider, autopair=True)

    async with service.start_quic_tunnel() as tunnel_result:
        if args.restart_remoted:
            resume_remoted_if_required()

        logger.info(f"QUIC Address: {tunnel_result.address}")
        logger.info(f"QUIC Port: {tunnel_result.port}")
        global rsd_port
        global rsd_host
        rsd_host = tunnel_result.address

        rsd_port = str(tunnel_result.port)


        while True:
            if terminate_tunnel_thread is True:
                return
            # wait user input while the asyncio tasks execute
            await asyncio.sleep(.5)


# Define the function to be executed in the thread
def run_tcp_tunnel(service_provider):

    try:
        asyncio.run(start_tcp_tunnel(service_provider))

        logger.info("run_tcp_tunnel completed")

    except Exception as e:
        logger.error(f"Error in run_tcp_tunnel: {e}")

    #return

# Define a function to start the tunnel thread
def start_tcp_tunnel_thread(service_provider):
    global terminate_tunnel_thread, tunnel_thread  # Declare the global variables
    terminate_tunnel_thread = False  # Set the value of the global variable
    tunnel_thread = threading.Thread(target=run_tcp_tunnel, args=(service_provider,), daemon=True)
    tunnel_thread.start()
    return

async def start_tcp_tunnel(service_provider: CoreDeviceTunnelProxy) -> None:

    logger.warning("Start USB TCP tunnel")

    global terminate_tunnel_thread
    if args.restart_remoted:
        stop_remoted_if_required()
    #install_driver_if_required()

    #service = await create_core_device_tunnel_service_using_rsd(service_provider, autopair=True)

    lockdown = create_using_usbmux(udid, autopair=True)
    #print("Lockdown for Windows: ", lockdown)
    service = CoreDeviceTunnelProxy(lockdown)
    #asyncio.run(tunnel_task(service, secrets=None, protocol=TunnelProtocol.TCP), debug=True)
    async with service.start_tcp_tunnel() as tunnel_result:
        logger.info(f"TCP Address: {tunnel_result.address}")
        logger.info(f"TCP Port: {tunnel_result.port}")
        global rsd_port
        global rsd_host
        rsd_host = tunnel_result.address

        rsd_port = str(tunnel_result.port)

        while True:
            if terminate_tunnel_thread is True:
                return
            # wait user input while the asyncio tasks execute
            await asyncio.sleep(.5)





def is_major_version_17_or_greater(version_string):
    # Check if the major version in the given version string is 17 or greater.
    try:
        major_version = int(version_string.split('.')[0])
        return major_version >= 17
    except (ValueError, IndexError):
        # Handle invalid version string or missing major version
        return False

def is_major_version_less_than_16(version_string):
    # Check if the major version in the given version string is 17 or greater.
    try:
        major_version = int(version_string.split('.')[0])
        return major_version < 16
    except (ValueError, IndexError):
        # Handle invalid version string or missing major version
        logger.error(f"Error: {ValueError}, {IndexError}")
        return False


def version_check(version_string):
    try:
        # Split the version string into major and minor version parts
        version_parts = version_string.split('.')

        # Extract the major and minor version parts
        major_version = int(version_parts[0])
        minor_version = int(version_parts[1]) if len(version_parts) > 1 else 0

        # Check if the version string satisfies the condition
        if major_version == 17 and 0 <= minor_version <= 3:
            if sys.platform == 'win32':
                logger.info("Checking Windows Driver requirement")
                logger.info("Driver is required")
            return True
        else:
            if sys.platform == 'win32':
                logger.info("Driver is not required")
                return False
            logger.info("MacOS - pass")
            return False



    except (ValueError, IndexError) as e:
        logger.error(f"Driver check error: {e}")
        # Handle invalid version string or missing major/minor version
        return False

def get_user_country():
    global user_locale, _country_cache, _country_cache_ts
    # The lookups below hit the network on Windows - cache for 5 minutes so
    # page refreshes stay fast.
    now = time.time()
    if _country_cache is not None and now - _country_cache_ts < 300:
        return _country_cache
    try:
        # Attempt to get the user's country using locale and pycountry
        user_locale, _ = locale.getlocale()

        if user_locale is None:
            logger.warning("User locale is None. Defaulting to IP geolocation service.")
            _country_cache = get_country_from_ip()
            _country_cache_ts = now
            return _country_cache

        country_code = user_locale.split('_')[-1]
        country = pycountry.countries.get(alpha_2=country_code)
        country_name = country.name if country else None

        # If country_name is None, try IP geolocation service as a fallback
        if country_name is None:
            logger.warning("Failed to retrieve country name using locale. Using IP geolocation service.")
            _country_cache = get_country_from_ip()
            _country_cache_ts = now
            return _country_cache
        else:
            _country_cache = country_name
            _country_cache_ts = now
            return country_name

    except Exception as e:
        logger.error(f"Error getting user country: {e}")
        return None


def get_country_from_ip():
    try:
        response = requests.get("http://ip-api.com/json/")
        if response.status_code == 200:
            data = response.json()
            country_name = data.get("country")
            if country_name:
                return country_name
            else:
                logger.warning("Failed to retrieve country name from IP geolocation service.")
        else:
            logger.error(f"Error: Unable to retrieve data. Status code: {response.status_code}")
            logger.warning("Setting to default country")
            country_name = "Spain"
        return country_name
    except Exception as e:
        logger.error(f"Error getting country from IP geolocation service: {e}")
        country_name = "Spain"
        return country_name
def get_devices_with_retry(max_attempts=10):
    if sys.platform == 'win32':
        logger.info(f"iOS Version: {ios_version}")
        if version_check(ios_version):
            if cli_install_wetest_drivers is not None:
                logger.info("Windows Driver Install Required")
                cli_install_wetest_drivers()
            else:
                logger.warning("pymobiledevice3 no longer exposes the WeTest driver install; "
                               "relying on the built-in USB tunnel driver")
    for attempt in range(1, max_attempts + 1):
        try:
            devices = asyncio.run(get_rsds(timeout))
            #dev1 = asyncio.run(get_rsds(timeout))
            #devices = asyncio.run(get_core_device_tunnel_services(timeout))
            #print("devices: ", devices)
            #print("dev1: ", dev1)
            if devices:
                return devices  # Return devices if the list is not empty
            else:
                logger.warning(f"Attempt {attempt}: No devices found")
        except Exception as e:
            logger.warning(f"Attempt {attempt}: Error occurred - {e}")
        time.sleep(1)  # Add a delay between attempts if needed
    raise RuntimeError("No devices found after multiple attempts.\n Ensure you are running GeoPort as sudo / Administrator \n Please see the FAQ: https://github.com/davesc63/GeoPort/blob/main/FAQ.md \n If you still have the error please raise an issue on github: https://github.com/davesc63/GeoPort/issues ")


def get_wifi_with_retry(max_attempts=10):
    global udid, wifi_address, wifi_port

    for attempt in range(1, max_attempts + 1):
        try:
            logger.info("Discovering Wifi Devices - This may take a while...")
            devices = asyncio.run(get_remote_pairing_tunnel_services(timeout))
            #devices = get_remote_pairing_tunnel_services(timeout)



            if devices:
                if udid:
                    for device in devices:
                        if device.remote_identifier == udid:
                            logger.info(f"Device found with udid: {udid}.")
                            wifi_address = device.hostname
                            wifi_port = device.port
                            return device
                else:
                    return devices
            else:
                logger.warning(f"Attempt {attempt}: No devices found")
        except Exception as e:
            logger.warning(f"Attempt {attempt}: Error occurred - {e}")

        # Add a delay between attempts
        time.sleep(1)

    raise RuntimeError("No devices found after multiple attempts. Please see the FAQ.")
def stop_tunnel_thread_internal():
    global terminate_tunnel_thread, tunnel_thread
    logger.info("stop tunnel thread")
    # Set the terminate flag to True to stop the thread
    terminate_tunnel_thread = True
    # Give the thread a moment to wind down so a replacement tunnel can be
    # started without two tunnels fighting over the device (issue #59).
    if tunnel_thread is not None and tunnel_thread.is_alive():
        tunnel_thread.join(timeout=2)


@app.route('/stop_tunnel', methods=['POST'])
def stop_tunnel_thread():
    stop_tunnel_thread_internal()
    return jsonify("Tunnel stopped")

@app.route('/api/data/<fuel_type>')
def get_fuel_type_data(fuel_type):
    selected_fuel_region = request.args.get('region', 'All')

    if api_data is None:
        logger.error("API Data is none, Fuel data is not available")
        return jsonify({}), 500  # Return an empty response with status code 500 (Internal Server Error)

    all_region_data = next(
        (region['prices'] for region in api_data['regions'] if region['region'] == selected_fuel_region), [])

    selected_data = next((entry for entry in all_region_data if entry['type'] == fuel_type), None)

    return jsonify(selected_data)


@app.route('/api/fuel_types')
def get_fuel_types():
    selected_fuel_region = request.args.get('region', 'All')

    if api_data is None:
        logger.error("API Data is none, sorry - Fuel data is not available")
        return jsonify({}), 500  # Return an empty response with status code 500 (Internal Server Error)

    all_region_data = next(
        (region['prices'] for region in api_data['regions'] if region['region'] == selected_fuel_region), [])

    fuel_types = set(entry['type'] for entry in all_region_data)

    return jsonify(list(fuel_types))


@app.route('/update_location', methods=['POST'])
def update_location():
    # Use 'request' to get the JSON data from the client
    data = request.get_json()

    # Convert latitude and longitude to float values
    lat = float(data['lat'])
    lng = float(data['lng'])

    global location
    location = f"{lat} {lng}"
    return 'Location updated successfully'

def check_pair_record(udid):
    global pair_record
    logger.info(f"Connection Type: {connection_type}")
    logger.info("Enable Developer Mode")

    home = get_home_folder()
    logger.info(f"Pair Record Home: {home}")

    filename = get_remote_pairing_record_filename(udid)
    logger.info(f"Pair Record File: {filename}")

    # pair_record = get_local_pairing_record(filename, home)
    pair_record = get_preferred_pair_record(udid, home)
    #logger.info(f"Pair Record: {pair_record}")
    return pair_record

def check_developer_mode(udid, connection_type):
    try:

        logger.warning(f"Check Developer Mode")

        lockdown = create_using_usbmux(udid, connection_type=connection_type, autopair=True)

        result = lockdown.developer_mode_status
        logger.info(f"Developer Mode Check result:  {result}")

        # Check if developer mode is enabled
        if result:
            logger.info("Developer Mode is true")
            return True
        else:
            logger.warning("Developer Mode is false")
            return False

    except subprocess.CalledProcessError as e:
        logger.error(f"Developer mode check failed: {e}")
        return False
    except Exception as e:
        # Device unplugged / stale connection - report cleanly instead of an
        # unhandled 500 (issue #189: "found raw devices, but UI not selectable").
        logger.error(f"Developer mode check error: {e}")
        return False


def enable_developer_mode(udid, connection_type):
    check_pair_record(udid)


    logger.info(f"Connection Type: {connection_type}")
    logger.info("Enable Developer Mode")

    home = get_home_folder()
    logger.info(f"Pair Record Home: {home}")
    #
    # filename = get_remote_pairing_record_filename(udid)
    # logger.info(f"Pair Record File: {filename}")
    #
    # pair_record = get_local_pairing_record(filename, home)
    # logger.info(f"Pair Record: {pair_record}")
    if connection_type == "Network":
        if pair_record is None:
            logger.error("Network: No Pair Record Found. Please use a USB cable first to create a pair record")
            return False, "No Pair Record Found. Please use a USB cable first to create a pair record"
    else:
        logger.error("No Pair Record Found. USB cable detected. Creating a pair record")
        pass
        #return False, "No Pair Record Found. Please use a USB cable first to create a pair record"

    lockdown = create_using_usbmux(
        udid,
        connection_type=connection_type,
        autopair=True,
        pairing_records_cache_folder=home)


    try:

        AmfiService(lockdown).enable_developer_mode()
        logger.info("Enable complete, mount developer image...")
        mount_developer_image()

    except DeviceHasPasscodeSetError:
        error_message = "Error: Device has a passcode set\n \n Please temporarily remove the passcode and run GeoPort again to enable Developer Mode \n \n Go to \"Settings - Face ID & Passcode\"\n"
        logger.error(f"{error_message}")
        return False, error_message

    # except Exception as e:  # Catch any other exception
    #     logger.error(f"An error occurred: {str(e)}")
    #     return False, f"An error occurred: {str(e)}"

    return True, None




@app.route('/enable_developer_mode', methods=['POST'])
def enable_developer_mode_route():
    try:
        global udid
        data = request.get_json()

        # Extract the udid from the request
        udid = data.get('udid', None)

        success, error_message = enable_developer_mode(udid, connection_type)

        if success:
            # Return a success response with any additional data needed
            return jsonify({'success': True, 'udid': udid})
        else:
            return jsonify({'error': error_message})

    except Exception as e:
        error_message = str(e)
        return jsonify({'error': error_message})



@app.route('/connect_device', methods=['POST'])
def connect_device():
    global udid, connection_type, ios_version, rsd_data, rsd_host, rsd_port, wifi_address

    # Only one connection attempt at a time - rapid double clicks used to start
    # two tunnels that fought each other (issue #59).
    if not connect_attempt_lock.acquire(blocking=False):
        return jsonify({'error': 'Connection attempt already in progress'})

    try:
        data = request.get_json()
        logger.info(f"Connect Device Data: {data}")

        # Extract the udid from the request
        udid = data.get('udid', None)
        ios_version = data.get('ios_version')

        connection_type = data.get('connType')

        if udid in rsd_data_map:
            if connection_type in rsd_data_map[udid]:
                logger.info(f"Connect_Device Map - Looking for {udid} in {connection_type}")
                rsd_data = rsd_data_map[udid][connection_type]

                rsd_host = rsd_data['host']
                rsd_port = rsd_data['port']

                logger.info(f"RSD in udid mapping is: {rsd_data}")

                # On iOS 17+ the cached entry points at a local tunnel port.
                # Verify it is still alive before reusing it - a stale entry
                # used to be handed back to the UI forever, which is why
                # "set location" silently stopped working (issues #141/#163/#172).
                if ios_version is not None and is_major_version_17_or_greater(ios_version):
                    if is_tunnel_endpoint_active(rsd_host, rsd_port):
                        logger.info("RSD already created. Reusing connection")
                        logger.info(f"RSD Data: {rsd_data}")
                        return jsonify({'rsd_data': rsd_data})
                    logger.warning("Cached RSD tunnel endpoint is stale - rebuilding")
                    clear_cached_rsd_data()
                else:
                    logger.info("RSD already created. Reusing connection")
                    logger.info(f"RSD Data: {rsd_data}")
                    return jsonify({'rsd_data': rsd_data})

            # If no matching entry found for the udid and desired connection type
            logger.info(f"No matching RSD entry found for udid: {udid} and connection type: {connection_type}")

        # Check if developer mode is enabled, and enable it if not
        #logger.info("Must be iOS17")
        if not check_developer_mode(udid, connection_type):
            # Display modal to inform the user and give options
            return jsonify({'developer_mode_required': 'True'})

        if connection_type == "USB":
            return connect_usb(data)

        elif connection_type == "Network":
            check_pair_record(udid)

            if pair_record is None:
                logger.error("No Pair Record Found. Please use a USB Cable to create one")
                return jsonify({"Error": "No Pair Record Found"})
            result = connect_wifi(data)
            #result = await connect_wifi(data)
            #return await connect_wifi(data)
            return result

        elif connection_type == "Manual":
            check_pair_record(udid)

            if pair_record is None:
                logger.error("No Pair Record Found. Please use a USB Cable to create one")
                return jsonify({"Error": "No Pair Record Found"})
            result = connect_wifi(data)
            # result = await connect_wifi(data)
            # return await connect_wifi(data)
            return result
        else:
            logger.error("Error: No matching connection type")
            return jsonify({"Error": "No matching connection type"})
    finally:
        connect_attempt_lock.release()

def check_rsd_data():
    max_attempts = 30
    attempts = 0
    while attempts < max_attempts:
        if rsd_host is not None and rsd_port is not None:
            return True  # Data is available
        time.sleep(1)
        attempts += 1
    return False  # Data is still None after all attempts


def get_cached_rsd_data():
    if udid in rsd_data_map and connection_type in rsd_data_map[udid]:
        return rsd_data_map[udid][connection_type]
    return None


def clear_cached_rsd_data():
    global rsd_host, rsd_port
    if udid in rsd_data_map and connection_type in rsd_data_map[udid]:
        del rsd_data_map[udid][connection_type]
        if not rsd_data_map[udid]:
            del rsd_data_map[udid]
    rsd_host = None
    rsd_port = None


def is_tunnel_endpoint_active(host, port, timeout_seconds=1.0):
    """Quick TCP connect check to see whether a local tunnel port is alive."""
    if not host or not port:
        return False
    try:
        with socket.create_connection((str(host), int(port)), timeout=timeout_seconds):
            return True
    except (OSError, ValueError) as e:
        logger.warning(f"Tunnel endpoint {host}:{port} not reachable - {e}")
        return False


def ensure_active_rsd_connection():
    """Make sure an iOS 17+ tunnel exists, rebuilding it if it went away.

    This is what keeps Set/Stop Location working after the tunnel dies
    (Wi-Fi hand-off, cable re-plug, remoted restarting, ...).
    """
    global rsd_host, rsd_port

    if ios_version is None or not is_major_version_17_or_greater(ios_version):
        return

    cached = get_cached_rsd_data()
    if cached is not None:
        if is_tunnel_endpoint_active(cached.get('host'), cached.get('port')):
            rsd_host = cached.get('host')
            rsd_port = cached.get('port')
            return
        logger.warning("Cached tunnel is stale - rebuilding")
        clear_cached_rsd_data()

    stop_tunnel_thread_internal()

    data = {'udid': udid, 'ios_version': ios_version, 'connType': connection_type}

    if connection_type == "USB":
        connect_usb(data)
    elif connection_type in ("Network", "Manual"):
        check_pair_record(udid)
        if pair_record is None:
            raise RuntimeError("No pair record found - reconnect the device")
        connect_wifi(data)
    else:
        raise RuntimeError(f"Unsupported connection type: {connection_type}")

    if not is_tunnel_endpoint_active(rsd_host, rsd_port):
        clear_cached_rsd_data()
        raise RuntimeError("Unable to establish an active device tunnel")


def release_connection_resources():
    stop_set_location_thread()
    stop_tunnel_thread_internal()
    clear_cached_rsd_data()
    global rsd_data
    rsd_data = None


@app.route('/connection_status', methods=['GET'])
def connection_status():
    """Report whether a device tunnel is currently active.

    The UI polls this on page load so a refresh no longer leaves stale
    Connected/Connecting states behind (issues #133/#140).
    """
    if ios_version is not None and is_major_version_17_or_greater(ios_version):
        cached = get_cached_rsd_data()
        connected = cached is not None and is_tunnel_endpoint_active(cached.get('host'), cached.get('port'))
    else:
        cached = get_cached_rsd_data()
        connected = cached is not None and lockdown is not None

    if connect_attempt_lock.locked():
        status = 'connecting'
    elif connected:
        status = 'connected'
    else:
        status = 'disconnected'

    # Last simulated location ("lat lng") so the UI can restore the map
    # marker after a page refresh.
    last_location = None
    try:
        if location:
            lat_s, lng_s = str(location).split()
            last_location = {'lat': float(lat_s), 'lng': float(lng_s)}
    except (ValueError, AttributeError):
        last_location = None

    return jsonify({
        'status': status,
        'udid': udid,
        'connection_type': connection_type,
        'ios_version': ios_version,
        'rsd_data': cached if connected else None,
        'last_location': last_location,
    })


@app.route('/release_connection', methods=['POST'])
def release_connection():
    release_connection_resources()
    return jsonify({'success': True})


def connect_usb(data):
    try:
        global udid, connection_type
        global ios_version
        global rsd_data, rsd_host, rsd_port

        logger.info(f"USB data: {data}")

        # Extract the udid from the request
        udid = data.get('udid', None)
        ios_version = data.get('ios_version')
        #ios_version = "17.0"
        connection_type = data.get('connType')
        rsd_host = None
        rsd_port = None

        if ios_version is not None and is_major_version_17_or_greater(ios_version):
            logger.info("iOS 17+ detected")


            logger.info(f"iOS Version: {ios_version}")
            if version_check(ios_version):
                if sys.platform == 'win32':
                    logger.warning("iOS is between 17.0 and 17.3.1, WHY?")
                    logger.warning("You should upgrade to 17.4+")
                    logger.error("We need to install a 3rd party driver for these versions")
                    logger.error("which may stop working at any time")
                    try:
                        devices = get_devices_with_retry()
                        logger.info(f"Devices: {devices}")
                        rsd = [device for device in devices if device.udid == udid]
                        if len(rsd) > 0:
                            rsd = rsd[0]
                        start_tunnel_thread(rsd)

                    except RuntimeError as e:
                        error_message = str(e)
                        logger.error(f"Error: {error_message}")
                        return jsonify({'error': 'No Devices Found'})
                else:
                    logger.warning("ios <17.4 on non-windows")
                    try:
                        devices = get_devices_with_retry()
                        logger.info(f"Devices: {devices}")
                        rsd = [device for device in devices if device.udid == udid]
                        if len(rsd) > 0:
                            rsd = rsd[0]
                        start_tunnel_thread(rsd)

                    except RuntimeError as e:
                        error_message = str(e)
                        logger.error(f"Error: {error_message}")
                        return jsonify({'error': 'No Devices Found'})

            else:
                global lockdown
                lockdown = create_using_usbmux(udid, autopair=True)
                logger.info(f"Create Lockdown {lockdown}")
                start_tcp_tunnel_thread(lockdown)


            #time.sleep(3)
            if not check_rsd_data():
                logger.error("RSD Data is None, Perhaps the tunnel isn't established")
            else:
                rsd_data = rsd_host, rsd_port
                logger.info(f"RSD Data: {rsd_data}")

            rsd_data_map.setdefault(udid, {})[connection_type] = {"host": rsd_host, "port": rsd_port}
            logger.info(f"Device Connection Map: {rsd_data_map}")
            return jsonify({'rsd_data': rsd_data})

        elif ios_version is not None and not is_major_version_17_or_greater(ios_version):
            rsd_data = ios_version, udid
            logger.info(f"RSD Data: {rsd_data}")

            # # Check if developer mode is enabled, and enable it if not
            # if not check_developer_mode(udid, connection_type):
            #     # Display modal to inform the user and give options
            #     return jsonify({'developer_mode_required': 'True'})

            # create LockdownServiceProvider
            #global lockdown
            lockdown = create_using_usbmux(udid, autopair=True)
            logger.info(f"Lockdown client = {lockdown}")
            #rsd_data = rsd_host, rsd_port
            rsd_host, rsd_port = rsd_data

            #rsd_data_map[udid] = rsd_data
            rsd_data_map.setdefault(udid, {})[connection_type] = {"host": rsd_host, "port": rsd_port}

            return jsonify({'message': 'iOS version less than 17', 'rsd_data': rsd_data})

        else:
            # Invalid ios_version
            return jsonify({'error': 'No iOS version present'})
    finally:
        logger.warning("Connect Device function completed")

def connect_wifi(data):
    try:
        global udid, wifi_address, connection_type, wifi_port
        global ios_version
        global rsd_data, rsd_host, rsd_port

        logger.info(f"Wifi data: {data}")

        # Extract the udid from the request
        udid = data.get('udid', None)
        ios_version = data.get('ios_version')
        #ios_version = "17.3.1"
        #wifi_address = data.get('wifiAddress')
        #logger.error(f"wifi address: {wifi_address}")
        connection_type = data.get('connType')

        if ios_version is not None and is_major_version_17_or_greater(ios_version):
            logger.info("iOS 17+ detected")

            if version_check(ios_version):
                try:
                    devices = get_wifi_with_retry()
                    #devices = "blah"
                    logger.info(f"Connect Wifi Devices: {devices}")
                    logger.info(f"Wifi Address:  {wifi_address}")
                except RuntimeError as e:
                    error_message = str(e)
                    logger.error(f"Error: {error_message}")
                    return jsonify({'error': 'No Devices Found'})


            rsd_host = None
            rsd_port = None

            # Run tun(devices) as a background task
            #asyncio.create_task(tun(devices))
            #await tun(devices)
            #start_wifi_tunnel_thread(devices)
            start_wifi_tunnel_thread()

            if not check_rsd_data():
                logger.error("RSD Data is None, Perhaps the tunnel isn't established")
            else:
                rsd_data = rsd_host, rsd_port
                logger.info(f"RSD Data: {rsd_data}")

            rsd_data_map.setdefault(udid, {})[connection_type] = {"host": rsd_host, "port": rsd_port}
            logger.info(f"Device Connection Map: {rsd_data_map}")
            return jsonify({'rsd_data': rsd_data})

        elif ios_version is not None and not is_major_version_17_or_greater(ios_version):
            rsd_data = ios_version, udid
            logger.info(f"RSD Data: {rsd_data}")

            # create LockdownServiceProvider
            global lockdown
            lockdown = create_using_usbmux(udid, connection_type=connection_type, autopair=True)
            #lockdown = create_using_tcp(wifi_address, udid)
            logger.info(f"Lockdown client = {lockdown}")

            rsd_data_map.setdefault(udid, {})[connection_type] = {"host": rsd_host, "port": rsd_port}

            return jsonify({'message': 'iOS version less than 17', 'rsd_data': rsd_data})

        else:
            # Invalid ios_version
            return jsonify({'error': 'No iOS version present'})
    finally:
        logger.warning("Connect Device function completed")




async def start_wifi_tcp_tunnel() -> None:

    logger.warning(f"Start Wifi TCP Tunnel")

    global terminate_tunnel_thread
    stop_remoted_if_required()
    #install_driver_if_required()

    # if sys.platform == 'win32':
    #     if is_driver_required:
    #         logger.warning("Installing WeTest Driver")
    #         cli_install_wetest_drivers()

    #service = await create_core_device_tunnel_service_using_remotepairing(udid, wifi_address, wifi_port)
    lockdown = create_using_usbmux(udid)
    service = CoreDeviceTunnelProxy(lockdown)

    async with service.start_tcp_tunnel() as tunnel_result:
        resume_remoted_if_required()

        logger.info(f'Identifier: {service.remote_identifier}')
        logger.info(f'Interface: {tunnel_result.interface}')
        logger.info(f'RSD Address: {tunnel_result.address}')
        logger.info(f'RSD Port: {tunnel_result.port}')
        global rsd_port
        global rsd_host
        rsd_host = tunnel_result.address

        rsd_port = str(tunnel_result.port)


        while True:
            if terminate_tunnel_thread is True:
                return
            # wait user input while the asyncio tasks execute
            await asyncio.sleep(.5)

async def start_wifi_quic_tunnel() -> None:

    logger.warning(f"Start Wifi QUIC Tunnel")

    global terminate_tunnel_thread
    stop_remoted_if_required()
    #install_driver_if_required()

    # if sys.platform == 'win32':
    #     if is_driver_required:
    #         logger.warning("Installing WeTest Driver")
    #         cli_install_wetest_drivers()
    #get_wifi_with_retry()
    service = await create_core_device_tunnel_service_using_remotepairing(udid, wifi_address, wifi_port)
    # lockdown = create_using_usbmux(udid)
    # service = CoreDeviceTunnelProxy(lockdown)

    async with service.start_quic_tunnel() as tunnel_result:
        resume_remoted_if_required()

        logger.info(f'Identifier: {service.remote_identifier}')
        logger.info(f'Interface: {tunnel_result.interface}')
        logger.info(f'RSD Address: {tunnel_result.address}')
        logger.info(f'RSD Port: {tunnel_result.port}')
        global rsd_port
        global rsd_host
        rsd_host = tunnel_result.address

        rsd_port = str(tunnel_result.port)


        while True:
            if terminate_tunnel_thread is True:
                return
            # wait user input while the asyncio tasks execute
            await asyncio.sleep(.5)

# Define a function to start the tunnel thread
def start_wifi_tunnel_thread():
    global terminate_tunnel_thread
    terminate_tunnel_thread = False  # Set the value of the global variable
    thread = threading.Thread(target=run_wifi_tunnel)
    thread.start()
    return

# Entry point for running the tunnel async function
def run_wifi_tunnel():
    try:
        if version_check(ios_version):
            asyncio.run(start_wifi_quic_tunnel())
        #TODO: or win32 / 17.0-17.3 special tunnel

        else:
            asyncio.run(start_wifi_tcp_tunnel())
        #await tun(devices)
    except Exception as e:
        logger.error(f"Error in run_wifi_tunnel: {e}")


@app.route('/mount_developer_image', methods=['POST'])
def mount_developer_image():
    try:

        global lockdown
        lockdown = create_using_usbmux(udid, autopair=True)
        logger.info(f"mount lockdown: {lockdown}")

        auto_mount(lockdown)

        return 'Developer image mounted successfully'
    except Exception as e:
        error_message = str(e)
        return jsonify({'error': error_message})

async def set_location_thread(latitude, longitude):
    global terminate_location_thread

    try:
        global rsd_host, rsd_port, udid, ios_version, connection_type

        if ios_version is not None and is_major_version_17_or_greater(ios_version):
            # Rebuild the tunnel if it went away since we connected (the main
            # cause of "set location silently stops working").
            ensure_active_rsd_connection()
            rsd_data = get_cached_rsd_data()
            logger.info(f"RSD Data: {rsd_host}:{rsd_port}")

            async with RemoteServiceDiscoveryService((rsd_host, rsd_port)) as sp_rsd:
                with DvtSecureSocketProxyService(sp_rsd) as dvt:
                    location_simulation = LocationSimulation(dvt)
                    location_simulation.clear()
                    location_simulation.set(latitude, longitude)
                    logger.warning("Location Set Successfully")
                    # Keep the loop alive (and responsive to Stop) without
                    # blocking this thread's event loop with time.sleep().
                    while not terminate_location_thread:
                        await asyncio.sleep(0.5)

        elif ios_version is not None and not is_major_version_17_or_greater(ios_version):
            with DvtSecureSocketProxyService(lockdown=lockdown) as dvt:
                location_simulation = LocationSimulation(dvt)
                location_simulation.clear()
                location_simulation.set(latitude, longitude)
                logger.warning("Location Set Successfully")
                while not terminate_location_thread:
                    await asyncio.sleep(0.5)

        await asyncio.sleep(1)  # Adjust sleep time according to your requirements

    except asyncio.CancelledError:
        # Handle cancellation gracefully
        pass
    except ConnectionResetError as cre:
        if "[Errno 54] Connection reset by peer" in str(cre):
            logger.error("The Set Location buffer is full. Try to 'Stop Location' to clear old connections")
    except Exception as e:
        logger.error(f"Error setting location: {e}")


# Function to start the set_location_thread in a separate thread
def start_set_location_thread(latitude, longitude):
    global terminate_location_thread, location_thread
    # Stop existing threads
    stop_set_location_thread()

    # Reset the terminate flag before starting the thread
    terminate_location_thread = False

    # Daemon thread so a wedged location loop can never keep the app alive
    # (issue #59: "no way to stop or refresh the connection"). The redundant
    # check_termination thread (which spun up a fresh asyncio loop every
    # second) is gone.
    location_thread = threading.Thread(
        target=lambda: asyncio.run(set_location_thread(latitude, longitude)),
        daemon=True)
    location_thread.start()


# Function to stop the location thread
def stop_set_location_thread():
    # Set the flag to indicate that the thread should stop
    global terminate_location_thread, location_thread
    terminate_location_thread = True
    if location_thread is not None and location_thread.is_alive():
        location_thread.join(timeout=2)




@app.route('/set_location', methods=['POST'])
def set_location():
    try:
        global rsd_data, rsd_host, rsd_port
        global location
        global udid, connection_type
        global ios_version

        if ios_version is not None and is_major_version_17_or_greater(ios_version):
            # Split the location string into latitude and longitude
            latitude, longitude = location.split()

            #asyncio.run(set_location_thread(latitude, longitude))
            stop_route_thread_internal(hold=False)  # a manual set wins over any route
            start_set_location_thread(latitude, longitude)

            return 'Location set successfully'

        elif ios_version is not None and not is_major_version_17_or_greater(ios_version):
            global lockdown
            # Split the location string into latitude and longitude
            latitude, longitude = location.split()

            mount_developer_image()
            #asyncio.run(set_location_thread(latitude, longitude))
            stop_route_thread_internal(hold=False)  # a manual set wins over any route
            start_set_location_thread(latitude, longitude)


            return 'Location set successfully'

        else:
            # Invalid ios_version
            return jsonify({'error': 'No iOS version present'})

    except Exception as e:
        error_message = str(e)
        return jsonify({'error': error_message})


@app.route('/stop_location', methods=['POST'])
async def stop_location():
    try:
        stop_set_location_thread()
        stop_route_thread_internal(hold=False)  # a manual stop wins over any route
        global rsd_data
        global location
        # Drop the remembered location so a page refresh after stopping
        # doesn't resurrect the stale "spoofing" UI state.
        location = None
        logger.info(f"stop set location data:  {rsd_data}")
        await clear_device_location()
        return 'Location cleared successfully'
    except Exception as e:
        error_message = str(e)
        return jsonify({'error': error_message})


# --- Server-side route playback ------------------------------------------------

def haversine_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in meters."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


async def _route_walk(sim, gen):
    """Walk the queued route at the configured speed. Runs in the route
    thread's event loop with one open DVT session for the whole route.
    Sleeping in small slices keeps Stop/Pause responsive."""
    global route_index, location
    points = list(route_points)
    speed = max(0.5, min(250.0, float(route_speed_kmh)))
    start = max(0, min(len(points) - 1, route_resume_start))
    try:
        sim.clear()
    except Exception as e:
        logger.warning(f"Could not clear previous location before route: {e}")
    for i in range(start, len(points)):
        if terminate_route_thread or route_generation != gen:
            break
        lat, lng = points[i]
        sim.set(lat, lng)
        location = f"{lat} {lng}"  # keep /connection_status fresh mid-route
        route_index = i
        if i < len(points) - 1:
            nxt = points[i + 1]
            dwell = haversine_m(lat, lng, nxt[0], nxt[1]) / (speed / 3.6)
        else:
            dwell = 10.0  # brief hold on the final point
        end = time.time() + dwell
        while time.time() < end and not terminate_route_thread and route_generation == gen:
            await asyncio.sleep(0.25)
    if not terminate_route_thread and route_generation == gen:
        # Natural finish: restore the device's real location.
        try:
            sim.clear()
        except Exception:
            pass
        location = None


async def route_playback_worker():
    global route_error, route_active, route_finished
    gen = route_generation
    try:
        if ios_version is not None and is_major_version_17_or_greater(ios_version):
            ensure_active_rsd_connection()
            rsd = get_cached_rsd_data()
            if rsd is None:
                raise RuntimeError("No active tunnel - connect the device first")
            async with RemoteServiceDiscoveryService((rsd['host'], rsd['port'])) as sp_rsd:
                with DvtSecureSocketProxyService(sp_rsd) as dvt:
                    await _route_walk(LocationSimulation(dvt), gen)
        elif ios_version is not None and not is_major_version_17_or_greater(ios_version):
            if lockdown is None:
                raise RuntimeError("No active device connection")
            with DvtSecureSocketProxyService(lockdown=lockdown) as dvt:
                await _route_walk(LocationSimulation(dvt), gen)
        else:
            raise RuntimeError("No iOS version present - connect a device first")
    except asyncio.CancelledError:
        pass
    except Exception as e:
        route_error = str(e)
        route_finished = True
        logger.error(f"Route playback error: {e}")
    finally:
        if route_generation == gen:
            route_active = False


def stop_route_thread_internal(hold=False):
    """Stop the route worker. hold=True keeps the last point spoofed (pause)."""
    global terminate_route_thread, route_thread, route_active, route_paused, route_finished
    terminate_route_thread = True
    if route_thread is not None and route_thread.is_alive():
        route_thread.join(timeout=3)
    route_active = False
    route_paused = bool(hold)
    route_finished = not hold


def start_route_thread():
    global route_thread, route_generation, terminate_route_thread, route_finished, route_error
    stop_route_thread_internal(hold=False)
    route_generation += 1
    terminate_route_thread = False
    route_active = True
    route_finished = False
    route_error = None
    logger.info(f"Starting route playback: {len(route_points)} points @ {route_speed_kmh} km/h from index {route_resume_start}")
    route_thread = threading.Thread(
        target=lambda: asyncio.run(route_playback_worker()), daemon=True)
    route_thread.start()


@app.route('/route_start', methods=['POST'])
def route_start():
    global route_points, route_speed_kmh, route_resume_start
    try:
        data = request.get_json(force=True) or {}
        raw = data.get('points') or []
        points = []
        for p in raw:
            try:
                if isinstance(p, dict):
                    points.append((float(p['lat']), float(p['lng'])))
                elif isinstance(p, (list, tuple)) and len(p) == 2:
                    points.append((float(p[0]), float(p[1])))
                else:
                    return jsonify({'error': 'invalid point format'}), 400
            except (TypeError, ValueError, KeyError):
                return jsonify({'error': 'invalid point format'}), 400
        if len(points) < 2:
            return jsonify({'error': 'need at least 2 route points'}), 400
        try:
            speed = float(data.get('speed_kmh', 5.0))
        except (TypeError, ValueError):
            speed = 5.0
        if not (0.5 <= speed <= 250):
            return jsonify({'error': 'speed_kmh must be between 0.5 and 250'}), 400
        try:
            start_index = int(data.get('start_index', 0))
        except (TypeError, ValueError):
            start_index = 0
        if not (0 <= start_index < len(points)):
            return jsonify({'error': 'start_index out of range'}), 400
        if udid is None:
            return jsonify({'error': 'connect a device first'}), 400
        with route_state_lock:
            route_points = points
            route_speed_kmh = speed
            route_resume_start = start_index
        stop_set_location_thread()  # the route takes over from any point spoof
        start_route_thread()
        return jsonify({'ok': True, 'points': len(points), 'speed_kmh': speed, 'start_index': start_index})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/route_stop', methods=['POST'])
async def route_stop():
    """Stop (and clear) the route, or pause it (hold=1 keeps the last point)."""
    global location
    try:
        data = request.get_json(silent=True) or {}
        hold = bool(data.get('hold', False))
        stop_route_thread_internal(hold=hold)
        if hold:
            return 'Route paused (location held)'
        location = None
        await clear_device_location()
        return 'Route stopped'
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/route_status')
def route_status():
    total = len(route_points)
    cur = None
    if total and 0 <= route_index < total:
        cur = {'lat': route_points[route_index][0], 'lng': route_points[route_index][1]}
    progress = ((route_index + 1) / total) if total and route_index >= 0 else 0.0
    return jsonify({
        'active': route_active,
        'paused': route_paused,
        'finished': route_finished,
        'error': route_error,
        'points': total,
        'index': route_index,
        'progress': round(min(1.0, progress), 4),
        'speed_kmh': route_speed_kmh,
        'current': cur,
    })


async def clear_device_location():
    """Clear the spoofed location on the device (best effort)."""
    global rsd_host, rsd_port
    cached = get_cached_rsd_data()
    if ios_version is not None and is_major_version_17_or_greater(ios_version):
        if cached is not None:
            rsd_host = cached['host']
            rsd_port = cached['port']
        if rsd_host is None or rsd_port is None or not is_tunnel_endpoint_active(rsd_host, rsd_port):
            logger.warning("No active tunnel - skipping on-device location clear")
            return
        async with RemoteServiceDiscoveryService((rsd_host, rsd_port)) as sp_rsd:
            with DvtSecureSocketProxyService(sp_rsd) as dvt:
                LocationSimulation(dvt).clear()
                logger.warning("Location Cleared Successfully")
    elif ios_version is not None and not is_major_version_17_or_greater(ios_version):
        if lockdown is None:
            return
        with DvtSecureSocketProxyService(lockdown=lockdown) as dvt:
            LocationSimulation(dvt).clear()
            logger.warning("Location Cleared Successfully")


# --- Health / watchdog ---------------------------------------------------------

@app.route('/health')
def health():
    """Lightweight status polled by the UI watchdog banner."""
    tunnel_ok = False
    try:
        cached = get_cached_rsd_data()
        if ios_version is not None and is_major_version_17_or_greater(ios_version):
            tunnel_ok = cached is not None and is_tunnel_endpoint_active(cached.get('host'), cached.get('port'))
        else:
            tunnel_ok = cached is not None and lockdown is not None
    except Exception:
        tunnel_ok = False
    return jsonify({
        'connected': bool(udid),
        'tunnel_ok': bool(tunnel_ok),
        'location_active': bool(location_thread is not None and location_thread.is_alive()),
        'route_active': bool(route_active),
        'route_paused': bool(route_paused),
        'route_error': route_error,
    })


# --- Saved location presets (~/.geoport/locations.json) -------------------------

def _locations_path():
    d = os.path.join(home_dir, '.geoport')
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, 'locations.json')


def _load_locations():
    try:
        with open(_locations_path(), encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_locations(items):
    with open(_locations_path(), 'w', encoding='utf-8') as f:
        json.dump(items, f, indent=2)


@app.route('/locations', methods=['GET'])
def get_saved_locations():
    return jsonify(_load_locations())


@app.route('/locations', methods=['POST'])
def save_location_preset():
    data = request.get_json(force=True) or {}
    name = str(data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    try:
        lat, lng = float(data['lat']), float(data['lng'])
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return jsonify({'error': 'valid name/lat/lng required'}), 400
    items = [i for i in _load_locations() if i.get('name') != name]
    items.append({'name': name, 'lat': lat, 'lng': lng})
    try:
        _save_locations(items)
    except Exception as e:
        return jsonify({'error': f'could not save: {e}'}), 500
    return jsonify(items)


@app.route('/locations/<path:name>', methods=['DELETE'])
def delete_location_preset(name):
    items = [i for i in _load_locations() if i.get('name') != name]
    _save_locations(items)
    return jsonify(items)


# --- Live activity log ----------------------------------------------------------

@app.route('/log_tail')
def log_tail():
    try:
        n = min(max(int(request.args.get('lines', 40)), 1), 200)
    except ValueError:
        n = 40
    try:
        with open(log_file_path, encoding='utf-8', errors='replace') as f:
            lines = f.readlines()[-n:]
        return Response(''.join(lines), mimetype='text/plain')
    except Exception as e:
        return Response(f'log unavailable: {e}', mimetype='text/plain', status=500)


# --- Optional API token (GEOPORT_TOKEN) ----------------------------------------

_PUBLIC_GET_PATHS = {'/', '/connection_status', '/health', '/route_status',
                     '/log_tail', '/locations', '/list_devices', '/api/fuel_types'}


@app.before_request
def _check_api_token():
    if not GEOPORT_TOKEN:
        return None
    if request.method in ('GET', 'HEAD') and request.path in _PUBLIC_GET_PATHS:
        return None
    provided = request.headers.get('X-GeoPort-Token') or request.args.get('token', '')
    if provided != GEOPORT_TOKEN:
        return jsonify({'error': 'unauthorized'}), 401
    return None


def get_github_version():
    global _version_cache, _version_cache_ts
    now = time.time()
    if _version_cache is not None and now - _version_cache_ts < 300:
        return _version_cache
    try:
        # Make a request to the GitHub API to get the content of CURRENT_VERSION file
        url = f'https://raw.githubusercontent.com/{GITHUB_REPO}/main/{CURRENT_VERSION_FILE}'
        response = requests.get(url)

        response.raise_for_status()

        # Parse the content of the file
        github_version = response.text.strip()

        _version_cache = github_version
        _version_cache_ts = now
        return github_version
    except requests.RequestException as e:

        return None


def get_github_broadcast():
    global _broadcast_cache, _broadcast_cache_ts
    now = time.time()
    if _broadcast_cache is not None and now - _broadcast_cache_ts < 300:
        return _broadcast_cache
    try:
        # Make a request to the GitHub API to get the content of BROADCAST file
        url = f'https://raw.githubusercontent.com/{GITHUB_REPO}/main/{BROADCAST_FILE}'
        logger.error(f"Github URL: {url}")

        response = requests.get(url, verify=False)
        logger.error(f"github response: {response}")
        #response.raise_for_status()

        # Parse the content of the file
        github_broadcast = response.text.strip()
        logger.error(f"GITHUB BROADCAST MESSAGE:")

        _broadcast_cache = github_broadcast
        _broadcast_cache_ts = now
        return github_broadcast
    except requests.RequestException as e:

        return None


def remove_ansi_escape_codes(text):
    ansi_escape = re.compile(r'\x1b[^m]*m')
    return ansi_escape.sub('', text)

async def get_network_devices():
# you can also query network lockdown instances using the following:
    async for ip, lockdown in get_mobdev2_lockdowns():
        print(ip, lockdown.short_info)

@app.route('/list_devices')
def py_list_devices():
    try:
        connected_devices = {}

        # Retrieve all devices
        all_devices = list_devices()
        #wifi_devices = None
        #wifi_devices = asyncio.run(get_network_devices())
        logger.info(f"\n\nRaw Devices:  {all_devices}\n")
        #logger.info(f"\n\nWifi Devices:  {wifi_devices}\n")


        if wifihost:
            udid = args.udid
            logger.warning(f"Wifi requested to {wifihost}")
            logger.warning(f"udid: {udid}")
            lockdown = create_using_tcp(hostname=wifihost, identifier=udid)

            # udid = lockdown.udid
            # print("wifi udid", udid)
            info = lockdown.short_info
            logger.warning(f"Wifi Short Info: {info}")
            # Modify the info dictionary to include wifiConState
            wifi_connection_state = lockdown.enable_wifi_connections = True
            info['wifiState'] = wifi_connection_state

            # Modify the info dictionary to include user locale
            info['userLocale'] = get_user_country()

            info['ConnectionType'] = 'Network'

            # Substitute "Network" with "Wifi" in the connection_type
            connection_type = "Manual Wifi"
            # if connection_type == "Network":
            #     connection_type = "Wifi"

            # If the serial already exists in the connected_devices dictionary
            if udid in connected_devices:
                # If the connection_type already exists under the serial, append the device to the list
                if connection_type in connected_devices[udid]:
                    connected_devices[udid][connection_type].append(info)
                # If the connection_type doesn't exist under the serial, create a new list with the device
                else:
                    connected_devices[udid][connection_type] = [info]
            # If the serial is new, create a new dictionary entry with the connection_type as a list
            else:
                connected_devices[udid] = {connection_type: [info]}






        # Iterate through all devices

        for device in all_devices:
            udid = device.serial
            connection_type = device.connection_type

            # Create lockdown and info variables
            #global lockdown
            lockdown = create_using_usbmux(udid, connection_type=connection_type, autopair=True)
            info = lockdown.short_info


            wifi_connection_state = lockdown.enable_wifi_connections

            if wifi_connection_state == False:
                logger.info("Enabling Wifi Connections")
                wifi_connection_state = lockdown.enable_wifi_connections = True
                logger.info(f"Wifi Connection State: True")

            # Modify the info dictionary to include wifiConState
            info['wifiState'] = wifi_connection_state

            # Modify the info dictionary to include user locale
            info['userLocale'] = get_user_country()

            # Substitute "Network" with "Wifi" in the connection_type
            if connection_type == "Network":
                connection_type = "Wifi"

            # If the serial already exists in the connected_devices dictionary
            if udid in connected_devices:
                # If the connection_type already exists under the serial, append the device to the list
                if connection_type in connected_devices[udid]:
                    connected_devices[udid][connection_type].append(info)
                # If the connection_type doesn't exist under the serial, create a new list with the device
                else:
                    connected_devices[udid][connection_type] = [info]
            # If the serial is new, create a new dictionary entry with the connection_type as a list
            else:
                connected_devices[udid] = {connection_type: [info]}

        logger.info(f"\n\nConnected Devices: {connected_devices}\n")

        # Check if running as sudo
        if current_platform == "darwin":
            if os.geteuid() != 0:
                logger.error("*********************** WARNING ***********************")
                logger.error("Not running as Sudo, this probably isn't going to work")
                logger.error("*********************** WARNING ***********************")
        return jsonify(connected_devices)

    except ConnectionAbortedError as e:
        logger.error(f"ConnectionAbortedError occurred: {e}")
        return {"error"}

    except Exception as e:
        error_message = str(e)
        return jsonify({'error': error_message})

def clear_geoport():
    logger.info("clear any GeoPort instances")
    substring = "GeoPort"

    for process in psutil.process_iter(['pid', 'name']):
        if substring in process.info['name']:
            logger.info(f"Found process: {process.info['pid']} - {process.info['name']}")

            # Terminate the process
            process.terminate()
    else:
        logger.warning("No GeoPort found")


def clear_old_geoport():
    logger.info("clear old GeoPort instances")
    substring = "GeoPort"

    current_pid = os.getpid()

    for process in psutil.process_iter(['pid', 'name']):
        if substring in process.info['name'] and process.info['pid'] != current_pid:
            logger.info(f"Found process: {process.info['pid']} - {process.info['name']}")

            # Terminate the process
            process.terminate()


def shutdown_server():
    logger.warning("shutdown server")
    asyncio.run(stop_location())
    stop_set_location_thread()
    stop_tunnel_thread_internal()
    clear_cached_rsd_data()
    cancel_async_tasks()
    terminate_threads()


    # Terminate the current process
    clear_geoport()

    logger.error("OS Kill")
    os.kill(os.getpid(), signal.SIGINT)
    list_threads()
    terminate_threads()
    logger.error("sys exit")
    os._exit(0)


def terminate_threads():
    """
    Terminate all threads.
    """
    for thread in threading.enumerate():
        if thread != threading.main_thread():
            logger.info(f"thread: {thread}")
            terminate_flag = threading.Event()
            terminate_flag.set()
            #thread.terminate()  # Terminate the thread

def list_threads():
    """
    Terminate all threads.
    """
    for thread in threading.enumerate():
        logger.info(f"thread: {thread}")
def cancel_async_tasks():
    try:
        #loop = asyncio.get_running_loop()
        tasks = asyncio.all_tasks()
        for task in tasks:
            logger.info(f"task: {task}")
            task.cancel()
    except RuntimeError as e:
        if "no running event loop" in str(e):
            logger.error("No running event loop found.")
        else:
            raise e  # Re-raise the error if it's not related to the event loop



@app.route('/exit', methods=['POST'])
def exit_app():
    logger.warning("Exit GeoPort")
    shutdown_server()
    # Send a response to the client immediately
    response = {"success": True, "message": "Server is shutting down..."}

    return jsonify(response)


@app.route('/')
def index():
    # global error_message
    fetch_api_data(api_url)
    user_locale = get_user_country()
    logger.info(f"Country: {user_locale}")
    logger.info(f"Current platform: {platform}")
    logger.info(f"App Version = {APP_VERSION_NUMBER}")
    logger.info(f"base dir =  {base_directory}")

    resp = make_response(render_template('map.html', version_message=None, github_broadcast=None,
                                         user_locale=user_locale, app_version_num=APP_VERSION_NUMBER,
                                         app_version_type=APP_VERSION_TYPE, error_message=error_message, current_platform=platform,
                                         sudo_message=sudo_message, api_token=GEOPORT_TOKEN))
    # Never serve a stale control-panel page from browser cache - the UI
    # state (connection, spoof location) is only meaningful when fresh.
    resp.headers['Cache-Control'] = 'no-store'
    return resp


def open_browser():
    time.sleep(2)  # Wait for the Flask app to start
    #webbrowser.open(f'http://localhost:{chosen_port}')
    browser = webbrowser.get()
    browser.open(f'http://localhost:{chosen_port}')


def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0
    # with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    #     try:
    #         s.bind((' ', port))
    #         return False  # Port is available
    #     except OSError:
    #         return True  # Port is already in use


# Define try_bind_listener_on_free_port function
def try_bind_listener_on_free_port():
    global chosen_port
    min_port = 49215
    max_port = 65535

    # Check if --port argument is provided
    if args.port:
        chosen_port = args.port
    else:
        chosen_port = flask_port

    if is_port_in_use(chosen_port):
        chosen_port = random.randint(min_port, max_port)
    logger.info(f'Serving: http://localhost:{chosen_port}')
    return chosen_port


if __name__ == '__main__':
    #create_geoport_folder()
    if is_windows:
        try:
            import pyi_splash

            pyi_splash.update_text('UI Loaded ...')
            logger.info("clear splash")
            pyi_splash.close()
        except:
            pass
        if not pyuac.isUserAdmin():
            print("Relaunching as Admin")
            pyuac.runAsAdmin()
    #else:




    chosen_port = try_bind_listener_on_free_port()

    # Check if --no-browser flag is provided
    if not args.no_browser:
        open_browser()
    else:
        logger.info("--no-browser flag passed")
        logger.info("Running without auto-browser popup")



    #threading.Thread(target=open_browser).start()

    # System tray icon (best effort - the app runs fine without one).
    def _tray_state():
        if route_active:
            line = f"Walking route: point {max(route_index, 0) + 1}/{len(route_points)}"
        elif route_paused:
            line = "Route paused (location held)"
        elif location_thread is not None and location_thread.is_alive():
            line = "Spoofing location"
        elif udid is not None:
            line = "Device connected"
        else:
            line = "No device connected"
        return "GeoPort", line

    try:
        import tray as geoport_tray
        geoport_tray.start_tray(_tray_state, f"http://localhost:{chosen_port}", shutdown_server)
    except Exception as e:
        logger.warning(f"Tray icon unavailable: {e}")

    # Bind to localhost only and never run the debug console: this is a
    # control plane for a paired iOS device, and 0.0.0.0 + debug=True made
    # it (and a Werkzeug RCE console) reachable from anywhere on the LAN.
    app.run(debug=False, use_reloader=False, port=chosen_port, host='127.0.0.1')




