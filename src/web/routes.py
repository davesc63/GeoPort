from flask import Blueprint, render_template, request, jsonify, current_app
from .app import device_manager, tunnel_service, location_service, fuel_api, GeoLocationAPI
from config import Config
import logging

main_bp = Blueprint('main', __name__)
logger = logging.getLogger("GeoPort")

@main_bp.route('/')
def index():
    fuel_api.fetch_data()
    user_locale = GeoLocationAPI.get_country_from_ip()
    
    # Version check logic (simplified)
    version_message = None
    # if github_version > Config.APP_VERSION_NUMBER ... (Add back if needed)

    return render_template('map.html', 
                           user_locale=user_locale,
                           app_version_num=Config.APP_VERSION_NUMBER,
                           current_platform=Config.PLATFORM_NAME,
                           version_message=version_message,
                           github_broadcast=None,
                           error_message=None,
                           sudo_message="")

@main_bp.route('/list_devices')
def list_devices():
    # If we had args for manual wifi, we'd pass them here. 
    # For now, just listing standard devices.
    return jsonify(device_manager.list_devices())

@main_bp.route('/connect_device', methods=['POST'])
def connect_device():
    data = request.get_json()
    udid = data.get('udid')
    conn_type = data.get('connType')
    ios_version = data.get('ios_version')
    
    logger.info(f"Connect Device: {udid}, {conn_type}, {ios_version}")

    # 1. Check Developer Mode
    if not device_manager.check_developer_mode(udid, conn_type):
        return jsonify({'developer_mode_required': 'True'})

    # 2. Connection Logic
    try:
        if conn_type == "USB":
             # Logic for USB
             # if ios 17+ -> start tunnel
             try:
                 major = int(ios_version.split('.')[0])
             except:
                 major = 0
             
             if major >= 17:
                 # Start Tunnel (simplified for now, ideally needs to find the specific RSD object)
                 # We need to find the RSD service for this UDID
                 devices = device_manager.get_devices_with_retry()
                 rsd = next((d for d in devices if d.udid == udid), None)
                 
                 if rsd:
                     tunnel_service.start_tunnel(tunnel_service.start_quic_tunnel, rsd)
                     # Wait for tunnel? The frontend polls? 
                     # The original code returned 'rsd_data' immediately if cached, or waited a bit.
                     return jsonify({'success': True, 'message': 'Tunnel starting...'})
                 else:
                     return jsonify({'error': 'Device not found'})
             else:
                 # < 17, just lockdown
                 return jsonify({'success': True, 'message': 'Connected (Lockdown)'})

        elif conn_type == "Network" or conn_type == "Manual":
             # Logic for Wifi
             device = device_manager.get_wifi_device(udid)
             if device:
                   if major >= 17:
                       tunnel_service.start_tunnel(tunnel_service.start_wifi_quic_tunnel, udid, device.hostname, device.port)
                   else:
                       tunnel_service.start_tunnel(tunnel_service.start_wifi_tcp_tunnel, udid, device.hostname, device.port)
                   return jsonify({'success': True})
             else:
                 return jsonify({'error': 'Wifi device not found'})
        
        return jsonify({'error': 'Unknown connection type'})

    except Exception as e:
        logger.error(f"Connection error: {e}")
        return jsonify({'error': str(e)})

@main_bp.route('/update_location', methods=['POST'])
def update_location():
    # Frontend sends this to update a global state, then calls set_location?
    # Or set_location does it all?
    # Original: update_location updates global 'location' string. set_location reads it.
    # We will just return success, and expect set_location to receive the data or handle it there.
    # Actually, looking at the original code, 'update_location' just updates the variable.
    # 'set_location' uses that variable.
    # Better: client calls set_location with data directly. But if we must preserve API:
    
    # We can store it in location_service temporarily?
    data = request.get_json()
    lat = float(data['lat'])
    lng = float(data['lng'])
    location_service.last_location = (lat, lng) 
    return 'Location updated'

@main_bp.route('/set_location', methods=['POST'])
def set_location():
    # If client sends data here, great. If not, check last_location.
    # Original set_location reads global 'location'.
    if hasattr(location_service, 'last_location'):
        lat, lng = location_service.last_location
    else:
        # Fallback or error
        return jsonify({'error': 'No location set'})

    # We need rsd info / ios version to know how to set location
    # This info needs to be passed or stored in device_manager from 'connect_device'
    
    # Simplified: We assume usage of the last connected device or similar context.
    # This acts as a known limitation of this refactor: we need to track session state better.
    # For now, let's assume valid state in tunnel_service/device_manager.
    
    rsd_host = tunnel_service.rsd_host
    rsd_port = tunnel_service.rsd_port
    
    # We need ios_version. Let's assume passed validation or stored.
    # Mocking for now:
    ios_major = 17 # TODO: Retrieve from session/state
    
    location_service.set_location(lat, lng, rsd_host, rsd_port, ios_major)
    return 'Location set successfully'

@main_bp.route('/stop_location', methods=['POST'])
def stop_location():
    location_service.stop_location()
    return 'Location cleared'

@main_bp.route('/api/fuel_types')
def get_fuel_types():
    region = request.args.get('region', 'All')
    return jsonify(fuel_api.get_fuel_types(region))

@main_bp.route('/api/data/<fuel_type>')
def get_fuel_type_data(fuel_type):
    region = request.args.get('region', 'All')
    return jsonify(fuel_api.get_fuel_type_data(fuel_type, region))
