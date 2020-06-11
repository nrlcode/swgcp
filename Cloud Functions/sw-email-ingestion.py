#requirements.txt
"""
# Function dependencies, for example:
# package>=version
firebase_admin
"""

import re
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

#Store the reservation information parsed from the email in Firestore
def store_in_firestore(fname, lname, reservation): 
    # Use the application default credentials
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    db = firestore.client()

    doc_ref = db.collection(u'Reservations').document(fname + " " + lname + " - " + reservation)
    doc_ref.set({
        u'first_name': fname,
        u'last_name': lname,
        u'reservation_number': reservation
    })

# Handler for receiving mail from CloudMailin
def on_incoming_message(request):
    request_json = request.get_json()
    print(request_json)
    print(request_json['headers']['subject'])

    subject = request_json['headers']['subject']
    body_plain = request_json['plain']

    fname, lname, reservation = None, None, None

    # Try to match `(5OK3YZ) | 22APR20 | DIA-OAK | Obama/Barack`
    legacy_email_subject_match = re.search(r"\(([A-Z0-9]{6})\).*\| (\w+ ?\w+\/\w+)", subject)

    # This matches a variety of new email formats which look like
    # Barack Obamas's 12/25 Oakland trip (ABC123)
    new_email_subject_match = re.search(r"(?:[Ff][Ww][Dd]?: )?(\w+).* (\w+)'s.*\(([A-Z0-9]{6})\)", subject)

    # ABC123 Barack Obama
    manual_email_subject_match = re.search(r"([A-Z0-9]{6})\s+(\w+) (\w+ ?\w+)", subject)

    if legacy_email_subject_match:
        print("Found a legacy reservation email: {}".format(subject))
        reservation = legacy_email_subject_match.group(1)
        lname, fname = legacy_email_subject_match.group(2).split('/')

    elif "Here's your itinerary!" in subject:
        print("Found an itinerary email: {}".format(subject))

        match = re.search(r"\(([A-Z0-9]{6})\)", subject)
        if match:
            reservation = match.group(1)

        print("Reservation found: {}".format(reservation))

        regex = r"PASSENGER([\w\s]+)Check in"
        match = re.search(regex, body_plain)

        if match:
            print("Passenger matched. Parsing first and last name")
            name_parts = match.group(1).strip().split(' ')
            fname, lname = name_parts[0], name_parts[-1]

    elif "Passenger Itinerary" in subject:
        #
        # AIR Confirmation: ABC123
        # *Passenger(s)*
        # BARACK/OBAMA W
        #
        print("Found ticketless itinerary email: {}".format(subject))
        regex = r"AIR Confirmation:\s+([A-Z0-9]{6})\s+\*Passenger\(s\)\*\s+(\w+\/\w+)"
        match = re.search(regex, body_plain)

        if match:
            print("Passenger matched. Parsing first and last name")
            reservation = match.group(1)
            lname, fname = match.group(2).strip().split('/')

    elif new_email_subject_match:
        print("Found new email subject match: {}".format(subject))
        fname = new_email_subject_match.group(1)
        lname = new_email_subject_match.group(2)
        reservation = new_email_subject_match.group(3)

    elif manual_email_subject_match:
        print("Found manual email subject match: {}".format(subject))
        reservation = manual_email_subject_match.group(1)
        fname = manual_email_subject_match.group(2)
        lname = manual_email_subject_match.group(3)

    # Short circuit we incorrectly match the first name
    # TODO(dw): Remove this when we fix this case in the parser
    if fname and fname.lower() in ('fwd', 'fw'):
        fname = None

    if not all([fname, lname, reservation]):
        print("Unable to find reservation for {}".format(subject))
        return "Failed"
    else:
        print("Passenger: {} {}, Confirmation Number: {}".format(
        fname, lname, reservation))
        store_in_firestore(fname, lname, reservation)
        return "Ok"