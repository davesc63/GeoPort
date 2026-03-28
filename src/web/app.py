from flask import Flask, render_template, jsonify
from config import Config
from core.device_manager import DeviceManager
from core.tunnel_service import TunnelService
from core.location_service import LocationService
from core.external_api import FuelAPI, GeoLocationAPI

# Global service instances (acting as singletons for the app)
device_manager = DeviceManager()
tunnel_service = TunnelService()
location_service = LocationService()
fuel_api = FuelAPI()

def create_app():
    app = Flask(__name__, template_folder='../templates', static_folder='../static') # Adjust paths if needed

    app.config.from_object(Config)

    # Register Blueprints or Routes
    from .routes import main_bp
    app.register_blueprint(main_bp)

    return app
