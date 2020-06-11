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

def schedule_checkin(flight_time, reservation):
    # Move back one day for the checkin time
    checkin_time = flight_time - timedelta(days=1)
    current_time = datetime.utcnow().replace(tzinfo=pytz.utc)
    # check to see if we need to sleep until 24 hours before flight
    if checkin_time > current_time:
        # calculate duration to sleep
        delta = (checkin_time - current_time).total_seconds() - CHECKIN_EARLY_SECONDS
        if delta > 300:
            print("Too early to check in.  Please reschedule 5 minutes before. {} seconds too early.".format(trunc(delta)))
            return "Too early to schedule function."
        else:
            # pretty print our wait time
            m, s = divmod(delta, 60)
            h, m = divmod(m, 60)
            print("Too early to check in.  Waiting {} hours, {} minutes, {} seconds".format(trunc(h), trunc(m), s))
            try:
                sleep(delta)
            except OverflowError:
                print("System unable to sleep for that long, try checking in closer to your departure date")
                sys.exit(1)
    data = reservation.checkin()
    for flight in data['flights']:
        for doc in flight['passengers']:
            print("{} got {}{}!".format(doc['name'], doc['boardingGroup'], doc['boardingPosition']))


def auto_checkin(reservation_number, first_name, last_name, verbose=False):
    r = Reservation(reservation_number, first_name, last_name, verbose)
    body = r.lookup_existing_reservation()

    # Get our local current time
    now = datetime.utcnow().replace(tzinfo=pytz.utc)

    # Kick off threads for handling legs of a trip asynchronously
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
            # Checkin with a thread
            t = Thread(target=schedule_checkin, args=(date, r))
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

def base64decoder(encoded_data):
    decoded_string = base64.b64decode(encoded_data)
    print(decoded_string)
    return decoded_string
    
    # code for handling tests from Cloud Scheduler and the "test" option from Cloud Functions
    # request_json = request.get_json()
    
    # if request_json:
    #     return request_json

    # # That's the hard way, i.e. Google Cloud Scheduler sending its JSON payload as octet-stream
    # if not request_json and request.headers.get("Content-Type") == "application/octet-stream":
    #     raw_request_data = request.data
    #     string_request_data = raw_request_data.decode("utf-8")
    #     request_json: dict = json.loads(string_request_data)

    # if request_json:
    #     return request_json

    # # Error code is obviously up to you
    # else:
    #     return "500"

def checkin_flight(event, context):
    try:
        event = base64decoder(event['data'])
        event = json.loads(event)
        if event['reservation_number'] == 'Priming':
            print("Priming")
            return 'Function primed.'
        else:
            reservation_number = event['reservation_number']
            first_name = event['first_name']
            last_name = event['last_name']
            print("{} {} - {}".format(first_name, last_name, reservation_number))
            verbose = False
        
        try:
            auto_checkin(reservation_number, first_name, last_name, verbose)
        except KeyboardInterrupt:
            print("Ctrl+C detected, canceling checkin")
            sys.exit()
   
    except Exception as e:
        sleep(8)
        raise e
