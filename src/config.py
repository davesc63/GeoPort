import os
import sys
import logging

class Config:
    APP_VERSION_NUMBER = "2.3.3"
    APP_VERSION_TYPE = "fuel"
    GITHUB_REPO = 'davesc63/GeoPort'
    CURRENT_VERSION_FILE = 'CURRENT_VERSION'
    BROADCAST_FILE = 'BROADCAST'
    API_URL = "https://projectzerothree.info/api.php?format=json"
    
    # Platform
    IS_WINDOWS = sys.platform == 'win32'
    PLATFORM_NAME = {
        'win32': 'Windows',
        'linux': 'Linux',
        'darwin': 'MacOS',
    }.get(sys.platform, 'Unknown')

    # Paths
    HOME_DIR = os.path.expanduser("~")
    BASE_DIRECTORY = getattr(sys, '_MEIPASS', os.path.abspath(os.path.dirname(sys.argv[0])))
    GEOPORT_FOLDER = os.path.join(HOME_DIR, 'GeoPort')

    # Defaults
    DEFAULT_FLASK_PORT = 54321
    DEFAULT_BONJOUR_TIMEOUT = 5 

    @staticmethod
    def setup_logging():
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler()]
        )
        logger = logging.getLogger("GeoPort")
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger('werkzeug').disabled = True
        return logger

    @staticmethod
    def ensure_geoport_folder():
        if not os.path.exists(Config.GEOPORT_FOLDER):
            os.makedirs(Config.GEOPORT_FOLDER)
            logging.getLogger("GeoPort").info(f"GeoPort Home: {Config.GEOPORT_FOLDER}")

        if Config.IS_WINDOWS:
            os.system(f"icacls {Config.GEOPORT_FOLDER} /grant Everyone:(OI)(CI)F")
        else:
            os.chmod(Config.GEOPORT_FOLDER, 0o777)
