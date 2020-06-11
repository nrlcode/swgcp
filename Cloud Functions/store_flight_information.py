
#requirements.txt
"""
# Function dependencies, for example:
# package>=version
coverage
datetime
docopts
pycodestyle
pytest
pytest-cov
pytest-mock
python-dateutil
pytz
requests
requests_mock
uuid
vcrpy
flask
firebase_admin
"""

import base64
from flask import request
import requests
import json
from datetime import datetime
from datetime import timedelta
from dateutil.parser import parse
from docopt import docopt
from math import trunc
import pytz
from threading import Thread
import sys
from time import sleep
from uuid import uuid1
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

CHECKIN_EARLY_SECONDS = 5
BASE_URL = 'https://mobile.southwest.com/api/'
CHECKIN_INTERVAL_SECONDS = 0.25
MAX_ATTEMPTS = 40

class Reservation():

    def __init__(self, number, first, last, verbose=False):
        self.number = number
        self.first = first
        self.last = last
        self.verbose = verbose

    @staticmethod
    def generate_headers():
        config_js = requests.get('https://mobile.southwest.com/js/config.js')
        if config_js.status_code == requests.codes.ok:
            modded = config_js.text[config_js.text.index("API_KEY"):]
            API_KEY = modded[modded.index(':') + 1:modded.index(',')].strip('"')
        else:
            print("Couldn't get API_KEY")
            sys.exit(1)

        USER_EXPERIENCE_KEY = str(uuid1()).upper()
        # Pulled from proxying the Southwest iOS App
        return {'Host': 'mobile.southwest.com', 'Content-Type': 'application/json', 'X-API-Key': API_KEY, 'X-User-Experience-Id': USER_EXPERIENCE_KEY, 'Accept': '*/*', 'X-Channel-ID': 'MWEB'}

    # You might ask yourself, "Why the hell does this exist?"
    # Basically, there sometimes appears a "hiccup" in Southwest where things
    # aren't exactly available 24-hours before, so we try a few times
    def safe_request(self, url, body=None):
        try:
            attempts = 0
            headers = Reservation.generate_headers()
            while True:
                if body is not None:
                    r = requests.post(url, headers=headers, json=body)
                else:
                    r = requests.get(url, headers=headers)
                data = r.json()
                if 'httpStatusCode' in data and data['httpStatusCode'] in ['NOT_FOUND', 'BAD_REQUEST', 'FORBIDDEN']:
                    attempts += 1
                    if not self.verbose:
                        print(data['message'])
                    else:
                        print(r.headers)
                        print(json.dumps(data, indent=2))
                    if attempts > MAX_ATTEMPTS:
                        sys.exit("Unable to get data, killing self")
                    sleep(CHECKIN_INTERVAL_SECONDS)
                    continue
                if self.verbose:
                    print(r.headers)
                    print(json.dumps(data, indent=2))
                return data
        except ValueError:
            # Ignore responses with no json data in body
            pass

    def load_json_page(self, url, body=None):
        data = self.safe_request(url, body)
        if not data:
            return
        for k, v in list(data.items()):
            if k.endswith("Page"):
                return v

    def with_suffix(self, uri):
        return "{}{}{}?first-name={}&last-name={}".format(BASE_URL, uri, self.number, self.first, self.last)

    def lookup_existing_reservation(self):
        # Find our existing record
        return self.load_json_page(self.with_suffix("mobile-air-booking/v1/mobile-air-booking/page/view-reservation/"))

    def get_checkin_data(self):
        return self.load_json_page(self.with_suffix("mobile-air-operations/v1/mobile-air-operations/page/check-in/"))

    def checkin(self):
        data = self.get_checkin_data()
        info_needed = data['_links']['checkIn']
        url = "{}mobile-air-operations{}".format(BASE_URL, info_needed['href'])
        print("Attempting check-in...")
        confirmation = self.load_json_page(url, info_needed['body'])
        return confirmation


def timezone_for_airport(airport_code):
    tzrequest = {'iata': airport_code,
                 'country': 'ALL',
                 'db': 'airports',
                 'iatafilter': 'true',
                 'action': 'SEARCH',
                 'offset': '0'}
    tzresult = requests.post("https://openflights.org/php/apsearch.php", tzrequest)
    airport_tz = pytz.timezone(json.loads(tzresult.text)['airports'][0]['tz_id'])
    return airport_tz

def write_to_firestore(flight_time, reservation_number, first_name, last_name):
    checkin_time = flight_time - timedelta(days=1)
    flightStr = flight_time.strftime('%d-%b-%Y (%H:%M:%S)')
    
    # Use the application default credentials
    
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    db = firestore.client()
    doc_ref = db.collection(u'Flights').document(first_name + " " + last_name + " (" + reservation_number + ") - " + flightStr)
    doc_ref.set({
        u'first_name': first_name,
        u'last_name': last_name,
        u'reservation_number': reservation_number,
        u'checkin_time':  checkin_time
    })



def auto_checkin(reservation_number, first_name, last_name, verbose=False):
    r = Reservation(reservation_number, first_name, last_name, verbose)
    body = r.lookup_existing_reservation()

    # Get our local current time
    now = datetime.utcnow().replace(tzinfo=pytz.utc)

    # kick of multiple threads to handle legs of the trip asynchronously
    threads = []

    # find all eligible legs for checkin
    for leg in body['bounds']:
        # calculate departure for this leg
        airport = "{}, {}".format(leg['departureAirport']['name'], leg['departureAirport']['state'])
        takeoff = "{} {}".format(leg['departureDate'], leg['departureTime'])
        airport_tz = timezone_for_airport(leg['departureAirport']['code'])
        date = airport_tz.localize(datetime.strptime(takeoff, '%Y-%m-%d %H:%M'))
        if date > now:
            # found a flight for checkin!
            print("Flight information found, departing {} at {}".format(airport, date.strftime('%b %d %I:%M%p')))
            # Write information to Firestore with a thread
            t = Thread(target=write_to_firestore, args=(date, reservation_number, first_name, last_name))
            t.daemon = True
            t.start()
            threads.append(t)

    # cleanup threads while handling Ctrl+C
    while True:
        if len(threads) == 0:
            break
        for t in threads:
            t.join(5)
            if not t.isAlive():
                threads.remove(t)
                break
    

def retrieve_from_firestore(data, context):
    """ Triggered by a change to a Firestore document.
    Args:
        data (dict): The event payload.
        context (google.cloud.functions.Context): Metadata for the event.
    """
    trigger_resource = context.resource

    first_name = data['value']['fields']['first_name']['stringValue']
    last_name = data['value']['fields']['last_name']['stringValue']
    reservation_number = data['value']['fields']['reservation_number']['stringValue']
    print("Found reservation for {} {} ({})".format(first_name,last_name,reservation_number))
    auto_checkin(reservation_number,first_name,last_name, verbose=False)
