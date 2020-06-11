# swgcp

This is still very much a work in progress, hoping to get to the stage where it can easily be deployed via Terraform to GCP.

## Requirements

These scripts are meant to be run with Python 3.7 in Cloud Functions on GCP. They utilize various components of GCP's services such as Pub/Sub, Firestore, and Cloud Scheduler in order to ingest emails, retrieve and store flight information, and eventually check you in for your flight.


## Contributors

Thanks to @pyro2927 and @DavidWittman for developing some of the code I used here.
