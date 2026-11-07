import sys
import os
import webbrowser
import threading
import time
import argparse
import logging
from web import create_app
from config import Config

# Setup logging globally
logger = Config.setup_logging()

def open_browser(port):
    time.sleep(2)
    webbrowser.open(f'http://localhost:{port}')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-browser', action='store_true', help='Skip auto opening the browser')
    parser.add_argument('--port', type=int, help='Specify port number')
    # Add other args calls if needed
    args = parser.parse_args()

    Config.ensure_geoport_folder()
    
    # Windows specific admin check
    if Config.IS_WINDOWS:
        try:
            import pyuac
            if not pyuac.isUserAdmin():
                 print("Relaunching as Admin")
                 pyuac.runAsAdmin()
        except ImportError:
            pass

    app = create_app()
    
    port = args.port if args.port else Config.DEFAULT_FLASK_PORT
    
    if not args.no_browser:
        threading.Thread(target=open_browser, args=(port,)).start()

    logger.info(f"Starting GeoPort on port {port}")
    app.run(debug=True, use_reloader=False, port=port, host='0.0.0.0')
