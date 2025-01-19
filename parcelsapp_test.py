import requests
import json
import time

apiKey = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1aWQiOiI2OGQyN2FlMC1kNjEwLTExZWYtYTU1NC0wOWRiODM2YmU3YWIiLCJzdWJJZCI6IjY3OGM2OGU3NTRjNzU3NjBjNzMwMDk0NSIsImlhdCI6MTczNzI1NTE0M30.DH6wql0WEIWUhmBfsWbQH15Axwi_c7xispr1UfiibLA'
trackingUrl = 'https://parcelsapp.com/api/v3/shipments/tracking'
shipments = [{'trackingId': '2016766712164144', 'language': 'en', 'country': 'Canada'}
             ]

# Initiate tracking request
response = requests.post(trackingUrl, json={'apiKey': apiKey, 'shipments': shipments})

if response.status_code == 200:
    response_json = response.json()
    # Get UUID from response
    uuid = response.json()['uuid']
    # Function to check tracking status with UUID
    def check_tracking_status():
        response = requests.get(trackingUrl, params={'uuid': uuid,'apiKey': apiKey })
        if response.status_code == 200:
            print(response.json())
            if response.json()['done']:
                print('Tracking complete')
            else:
                print('Tracking in progress...')
                time.sleep(1) # sleep for N sec
                check_tracking_status()
        else:
            print(response.text)
    check_tracking_status()
else:
    print(response.text)
    