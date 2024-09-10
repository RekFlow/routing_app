import json
import re
from functools import lru_cache
import logging
from flask import Flask, render_template, request, jsonify, send_from_directory
import requests
import googlemaps
from dotenv import load_dotenv
import os
from time import time

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

# Initialize the Flask app
app = Flask(__name__)

# Get the Google Maps API key from the .env file
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')

# Initialize Google Maps client using the API key
gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)

# Correct JSON URL for provider data
json_url = 'https://www22.anthem.com/CMS/PROVIDERS_FL.json'

@lru_cache(maxsize=1)
def fetch_provider_data():
    try:
        response = requests.get(json_url)
        response.raise_for_status()
        provider_data = response.json()

        providers = []
        for item in provider_data:
            # Extract name
            name = f"{item.get('name', {}).get('first', '')} {item.get('name', {}).get('last', '')}".strip()
            
            # Extract address and zip code
            addresses = item.get('addresses', [{}])
            address = addresses[0].get('address', '') if addresses else ''
            zip_code = str(addresses[0].get('zip', '')).strip() if addresses else ''

            # Create provider info dictionary
            provider_info = {
                'name': name,
                'address': address,
                'specialty': item.get('specialty', ''),
                'insurance_accepted': item.get('plans', []),
                'contact': addresses[0].get('phone', '') if addresses else '',
                'zip_code': zip_code
            }
            providers.append(provider_info)

        logging.info(f"Successfully fetched {len(providers)} providers")
        logging.debug(f"Sample provider data: {json.dumps(providers[:2], indent=2)}")
        return providers
    except requests.RequestException as e:
        logging.error(f"Error fetching provider data: {str(e)}")
        return []
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON data: {str(e)}")
        return []

# Home route that serves the index.html file
@app.route('/')
def home():
    return render_template('index.html')

# Rate limiting for Google Maps API calls
last_call = 0
call_count = 0
RATE_LIMIT = 50  # Maximum calls per second

def rate_limited_geocode(address):
    global last_call, call_count
    current_time = time()
    if current_time - last_call >= 1:
        last_call = current_time
        call_count = 0
    if call_count >= RATE_LIMIT:
        return None
    call_count += 1
    return gmaps.geocode(address)

# Search route to filter providers based on user input
@app.route('/search', methods=['POST'])
def search():
    user_location = request.form.get('location', '').strip()

    logging.info(f"Search request: location={user_location}")

    try:
        providers = fetch_provider_data()

        filtered_providers = []
        for provider in providers:
            logging.debug(f"Checking provider: {provider['name']}, ZIP: {provider['zip_code']}")
            
            provider_zip = provider['zip_code'].strip()
            if user_location and not provider_zip.startswith(user_location):
                logging.debug(f"ZIP code mismatch: {provider_zip} doesn't start with {user_location}")
                continue
            
            filtered_providers.append(provider)
            logging.debug(f"Provider matched: {provider['name']}")

        logging.info(f"Found {len(filtered_providers)} matching providers")

        # Limit to first 10 providers and geocode their addresses
        for provider in filtered_providers[:10]:
            geocode_result = rate_limited_geocode(provider['address'])
            if geocode_result:
                lat_lng = geocode_result[0]['geometry']['location']
                provider['lat'] = lat_lng['lat']
                provider['lng'] = lat_lng['lng']
            else:
                provider['lat'] = None
                provider['lng'] = None

        return jsonify(filtered_providers[:10])

    except Exception as e:
        logging.error(f"Error in search: {str(e)}")
        return jsonify({"error": "An error occurred during the search process"}), 500

# Route planning based on user-selected stops
@app.route('/route', methods=['POST'])
def route():
    user_location = request.form.get('user_location', '')  # Starting point
    stops = request.form.getlist('stops')  # List of selected stops (practice addresses)

    try:
        # Get directions using Google Maps API
        waypoints = '|'.join(stops[:-1])  # Waypoints (all but the final stop)
        directions_result = gmaps.directions(user_location, stops[-1], waypoints=waypoints, optimize_waypoints=True)
        return jsonify(directions_result)
    except Exception as e:
        logging.error(f"Error getting directions: {str(e)}")
        return jsonify({"error": "Unable to calculate route"}), 500

# Debug route to view raw provider data
@app.route('/debug/raw_data')
def debug_raw_data():
    try:
        response = requests.get(json_url)
        response.raise_for_status()
        return response.text, 200, {'Content-Type': 'application/json'}
    except requests.RequestException as e:
        logging.error(f"Error fetching raw provider data: {str(e)}")
        return jsonify({"error": "Unable to fetch raw data"}), 500

# Run the app
if __name__ == '__main__':
    app.run(debug=True)