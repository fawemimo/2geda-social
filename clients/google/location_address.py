import os
import requests
# Client for interacting with Google Maps Location/Geocoding services.

class GoogleLocation:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("GOOGLE_MAPS_API_KEY")
# Reverse geocodes the given latitude and longitude into address components.

    def get_address(self, latitude: float, longitude: float) -> dict | None:
        if not self.api_key:
            raise ValueError("Google Maps API key is missing. Set GOOGLE_MAPS_API_KEY in your environment.")

        url = os.getenv("GOOGLE_MAPS_GEOCODE_URL")
        params = {
            "latlng": f"{latitude},{longitude}",
            "key": self.api_key
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "OK" and data.get("results"):
                result = data["results"][0]
                components = result.get("address_components", [])

                city = next((c["long_name"] for c in components if "locality" in c["types"]), None)
                state = next((c["long_name"] for c in components if "administrative_area_level_1" in c["types"]), None)
                country = next((c["long_name"] for c in components if "country" in c["types"]), None)

                return {
                    "formatted_address": result.get("formatted_address"),
                    "city": city,
                    "state": state,
                    "country": country
                }
            return None
        except requests.RequestException:
            return None

