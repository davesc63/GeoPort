import requests
import logging
from config import Config

logger = logging.getLogger("GeoPort")

class FuelAPI:
    def __init__(self, api_url=Config.API_URL):
        self.api_url = api_url
        self.api_data = None

    def fetch_data(self):
        try:
            response = requests.get(self.api_url, verify=False)
            self.api_data = response.json()
            return self.api_data
        except Exception as e:
            logger.error(f"Error fetching API data: {e}")
            return None

    def get_fuel_type_data(self, fuel_type, region='All'):
        if not self.api_data:
             return None
        
        all_region_data = next(
            (r['prices'] for r in self.api_data['regions'] if r['region'] == region), [])
        
        return next((entry for entry in all_region_data if entry['type'] == fuel_type), None)

    def get_fuel_types(self, region='All'):
        if not self.api_data:
            return []
            
        all_region_data = next(
            (r['prices'] for r in self.api_data['regions'] if r['region'] == region), [])
            
        return list(set(entry['type'] for entry in all_region_data))

class GeoLocationAPI:
    @staticmethod
    def get_country_from_ip():
        try:
            response = requests.get("http://ip-api.com/json/")
            if response.status_code == 200:
                return response.json().get("country", "Spain")
        except Exception as e:
            logger.error(f"GeoIP Error: {e}")
        return "Spain"
