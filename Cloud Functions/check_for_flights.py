#requirements.txt
"""
# Function dependencies, for example:
# package>=version
coverage
datetime
pycodestyle
pytest
pytest-cov
pytest-mock
python-dateutil
pytz
firebase_admin
google-cloud-pubsub
"""

import base64
import json
from datetime import datetime
from datetime import timedelta
from dateutil.parser import parse
import pytz
import sys
from time import sleep
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
from google.cloud import pubsub_v1

def base64decoder(encoded_data):
    decoded_string = base64.b64decode(encoded_data)
    print(decoded_string)
    return decoded_string
    


def find_flights(event, context):
    try:
        # Set current time to compare against flight records
        current_time=datetime.utcnow()
        # Move forward one minute to check within the next minute
        current_time_plus1=current_time + timedelta(minutes=1)        

        #Decode message from Cloud Scheduler
        event = base64decoder(event['data'])
        event = json.loads(event)
        if event['reservation_number'] == 'Priming':
            print("Checking for flights...")
        else:
            print("Cloud Scheduler sent unidentified data.")

        if not firebase_admin._apps:
            firebase_admin.initialize_app()
        db = firestore.client()

        flights = db.collection(u'Flights').where(u'checkin_time', u'>=', current_time).where(u'checkin_time', u'<=', current_time_plus1).stream()

        # To Do
        project_id = "GCPPROJECT"
        topic_id = "YOURTOPIC"

        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(project_id, topic_id)


        flights_detected = False

        # For any flights found, send them to Pub/Sub
        for flight in flights:
            flights_detected = True
            del flight._data['checkin_time']
            flight_json = json.dumps(flight._data)
            print("Found flight: " + flight.id)
            message = flight_json
            # Data must be a bytestring
            message = message.encode("utf-8")
            print(message)
            # When you publish a message, the client returns a future.
            future = publisher.publish(topic_path, data=message)
            print(future.result())

        if flights_detected == False:
            print("No flights flound")


        return("Checked for flights.")

    except Exception as e:
        sleep(8)
        raise e