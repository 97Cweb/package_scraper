import imaplib
import email
import json
import requests
from datetime import datetime
from email.header import decode_header
from email.utils import parsedate_to_datetime
from openai import OpenAI
from bs4 import BeautifulSoup
import regex as re
import os
import time
import barcode
from barcode.writer import ImageWriter

# File to store the last scan date
LAST_SCAN_FILE = "last_scan_date.txt"

# Function to read credentials from secrets.txt
def read_credentials(filename):
    with open(filename, 'r') as file:
        lines = file.readlines()
        username = lines[0].strip()
        password = lines[1].strip()
        openai_org = lines[2].strip()
        openai_project = lines[3].strip()
        api_key = lines[4].strip()
        parcel_key = lines[5].strip()
        postal_code = lines[6].strip()
    return username, password, openai_org, openai_project, api_key,parcel_key,postal_code

# Function to connect to the IMAP server
def connect_to_email_server(server, username, password):
    try:
        mail = imaplib.IMAP4_SSL(server)
        mail.login(username, password)
        return mail
    except Exception as e:
        print(f"Failed to connect to the email server: {e}")
        return None

# Function to get the last scan date
def get_last_scan_date():
    """Retrieve the last scan date from the file."""
    if os.path.exists(LAST_SCAN_FILE):
        with open(LAST_SCAN_FILE, "r") as file:
            date_str = file.readline().strip()
            try:
                return datetime.fromisoformat(date_str)
            except Exception as e:
                print(f"Error parsing last scan date: {e}")
                return None
    return None

# Function to save the last scan date
def save_last_scan_date(date):
    """Save the last scan date to the file."""
    with open(LAST_SCAN_FILE, "w") as file:
        file.write(date.isoformat())

# Function to fetch email IDs from the inbox
def fetch_email_ids(mail, folder="inbox", scan_all=False):
    """
    Fetch email IDs from the inbox.
    If scan_all is False, only fetch emails with a date greater than the last scan date.
    """
    try:
        mail.select(folder)
        status, messages = mail.search(None, 'ALL')
        if status != "OK":
            print("No messages found!")
            return []

        email_ids = messages[0].split()
        print(f"Found {len(email_ids)} emails.")
        if scan_all:
            print("returning all email ids")
            return email_ids

        # Retrieve emails with a date greater than the last scan date
        last_scan_date = get_last_scan_date()
        if last_scan_date is None:
            return email_ids  # No prior scan date, process all emails

        filtered_ids = []
        
        for i in reversed(range(len(email_ids))):
            email_id = email_ids[i]
            print(f"checking: {i}")
            status, msg_data = mail.fetch(email_id, '(BODY.PEEK[HEADER.FIELDS (DATE)])')
            if status != "OK":
                print(f"Failed to fetch email date for ID {email_id}")
                continue

            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg_date = email.message_from_bytes(response_part[1]).get("Date")
                    if msg_date:
                        try:
                            email_date = parsedate_to_datetime(msg_date)
                            if email_date <= last_scan_date:
                                print("Encountered email older than last scan date. Stopping.")
                                return filtered_ids  # Stop processing earlier emails
                            filtered_ids.append(email_id)
                        except Exception as e:
                            print(f"Error parsing email date: {e}")
        return filtered_ids
    except Exception as e:
        print(f"Failed to fetch email IDs: {e}")
        return []

# Function to fetch and process a single email
def process_email(mail, email_id, openai_client):
    """
    Process a single email and extract order and shipping details.
    """
    try:
        email_data = fetch_and_parse_email(mail, email_id)
        if not email_data:
            return None

        # Ignore specific senders (e.g., PayPal)
        if any(domain in email_data.get("from", "").lower() for domain in ["amazon.com", "amazon.ca","paypal.com"]):
            print(f"Ignored email from {email_data['from']}")
            return None

        # Extract order and shipping information using GPT
        parsed_data = extract_with_gpt(email_data, openai_client)
        if not parsed_data or "order_number" not in parsed_data:
            print(f"Skipped email: No order number found for email ID {email_id}")
            return None

        # Merge extracted data into email_data
        email_data.update(parsed_data)
        return email_data

    except Exception as e:
        print(f"Failed to process email ID {email_id}: {e}")
        return None

def fetch_and_parse_email(mail, email_id):
    """
    Fetch and parse an email by ID.
    """
    try:
        status, msg_data = mail.fetch(email_id, '(RFC822)')
        if status != "OK":
            print(f"Failed to fetch email ID {email_id}")
            return None

        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])

                # Extract headers
                subject, encoding = decode_header(msg.get("Subject", ""))[0]
                subject = subject.decode(encoding if encoding else "utf-8") if isinstance(subject, bytes) else subject
                email_from = msg.get("From")
                date_received = parse_email_date(msg.get("Date"))

                # Extract body
                body = extract_email_body(msg)
                cleaned_body = clean_email_body(body)

                return {
                    "subject": subject,
                    "from": email_from,
                    "date_received": date_received,
                    "body": cleaned_body,
                }

    except Exception as e:
        print(f"Error fetching or parsing email ID {email_id}: {e}")
        return None



def parse_email_date(date_header):
    """
    Parse the email date header into ISO format.
    """
    try:
        if date_header:
            return parsedate_to_datetime(date_header).isoformat()
    except Exception as e:
        print(f"Error parsing email date: {e}")
    return None


# Function to extract the email body
def extract_email_body(msg):
    body = ""
    try:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() in ["text/plain", "text/html"]:
                    body += part.get_payload(decode=True).decode("utf-8", "ignore")
        else:
            body = msg.get_payload(decode=True).decode()
    except Exception as e:
        print(f"Could not decode email body: {e}")
    return body

# Function to clean the email body
def clean_email_body(body):
    try:
        soup = BeautifulSoup(body, "html.parser")
        # Remove script and style elements
        for element in soup(["script", "style"]):
            element.decompose()
        text = soup.get_text()
        text = re.sub(r"\{(?:[^{}]*|(?R))*\}", "", text)  # Remove nested CSS
        text = re.sub(r"[^\x20-\x7E\n]", "", text).strip()
        text = re.sub(r"\n{2,}", "\n", text)  # Normalize newlines
        return text
    except Exception as e:
        print(f"Error cleaning email body: {e}")
        return ""

# Function to process GPT response
def extract_with_gpt(email_data, openai_client):
    """
    Use GPT to extract order and shipping details from the email.
    Includes logic to handle Amazon-specific emails and parse their statuses.
    """
    try:
        prompt = f"""
        Extract the order number, tracking/shipping number, company, and list of items in shipment from the following email.
        Provide the output as a JSON object with the keys: order_number, tracking_number, company, status, delivery_date, and items.
        Carriers such as Canada Post are not the company; for example, Amazon is the company. Only return the json, do not describe it

        Email Data:
        Subject: {email_data['subject']}
        From: {email_data['from']}
        Body: {email_data['body']}
        """

        completion = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ]
        )
        response = completion.choices[0].message.content
        return process_gpt_response(response)

    except Exception as e:
        print(f"Error during GPT extraction: {e}")
        return {
            "order_number": None,
            "tracking_number": None,
            "status": None,
            "delivery_date": None,
            "items": [],
        }


# Function to handle GPT response
def process_gpt_response(response):
    try:
        cleaned_response = response.replace('```json\n', '').replace('```', '')
        parsed_json = json.loads(cleaned_response)
        if not parsed_json.get("order_number"):
            return {}  # Skip if no order number
        return parsed_json
    except Exception as e:
        print(f"Failed to process GPT response: {e}")
        return {}

def fetch_and_save_email_ids(folder="inbox", scan_all=False):
    """
    Fetch email IDs based on the folder and scan mode and save them to a file.
    """
    username, password, _, _, _,_,_ = read_credentials("secrets.txt")
    mail = connect_to_email_server("imap.gmail.com", username, password)
    if mail is None:
        return
    try:
        email_ids = fetch_email_ids(mail, folder, scan_all)
        print(f"Fetched {len(email_ids)} email IDs.")
        with open("email_ids.txt", "w") as file:
            for email_id in email_ids:
                file.write(f"{email_id.decode()}\n")  # Save as string
    finally:
        mail.logout()
        
def process_and_save_emails(openai_client, folder="inbox"):
    """
    Process emails based on saved email IDs and merge the results with existing JSON data.
    Updates the last scan date if successful.
    """
    username, password, _, _, _,_,_ = read_credentials("secrets.txt")
    mail = connect_to_email_server("imap.gmail.com", username, password)
    if mail is None:
        return
        
    mail.select(folder)
    status, messages = mail.search(None, 'ALL')
    if status != "OK":
        print("No messages found!")
        return

    try:
        # Read email IDs from file
        try:
            with open("email_ids.txt", "r") as file:
                email_ids = [line.strip() for line in file.readlines()]
        except FileNotFoundError:
            print("No email IDs file found.")
            return

        # Load existing emails from JSON file
        if os.path.exists("emails.json"):
            with open("emails.json", "r", encoding="utf-8") as file:
                existing_emails = json.load(file)
        else:
            existing_emails = []

        # Create a lookup dictionary for existing emails by order_number
        existing_emails_dict = {
            email.get("order_number"): email
            for email in existing_emails
            if email.get("order_number")
        }

        # Process new emails and merge data
        new_emails = []
        for email_id in reversed(email_ids):
            email_data = process_email(mail, email_id.encode(), openai_client)
            if email_data:
                order_number = email_data.get("order_number")
                if order_number:
                    # Update existing entry or add a new one
                    if order_number in existing_emails_dict:
                        existing_emails_dict[order_number].update(email_data)
                    else:
                        existing_emails_dict[order_number] = email_data
                else:
                    # Skip emails without an order_number
                    print(f"Skipped email: No order number found for email ID {email_id}")
                new_emails.append(email_data)

        if new_emails:
            # Save merged emails to JSON
            merged_emails = list(existing_emails_dict.values())
            with open("emails.json", "w", encoding="utf-8") as file:
                json.dump(merged_emails, file, indent=4, ensure_ascii=False)

            # Update the last scan date
            latest_date = max(
                datetime.fromisoformat(email["date_received"])
                for email in new_emails
                if "date_received" in email
            )
            save_last_scan_date(latest_date)

    finally:
        mail.logout()


def save_emails_to_json(emails, filename):
    """
    Save processed email data to a JSON file.
    """
    try:
        with open(filename, "w", encoding="utf-8") as file:
            json.dump(emails, file, ensure_ascii=False, indent=4)
        print(f"Saved emails to {filename}.")
    except Exception as e:
        print(f"Error saving emails to JSON: {e}")
        


import requests
import json


def update_package_status(api_key,postal_code):
    """
    Check the status of packages using the Ship24 API.
    Updates the email data with the tracking status and returns a list of delivered packages.
    """
    delivered_packages = []
    tracking_url = 'https://parcelsapp.com/api/v3/shipments/tracking'

    try:
        # Load the saved emails
        with open("emails.json", "r", encoding="utf-8") as file:
            emails = json.load(file)
            
        # Create a lookup dictionary by order_number for efficient updates
        email_lookup = {email.get("order_number"): email for email in emails if email.get("order_number")}


        # Collect packages to track
        shipments = [
            {
                "trackingId": email["tracking_number"],
                "language": "en",
                "country": "Canada",
                "zipcode": postal_code
            }
            for email in emails
            if "tracking_number" in email
            and email["tracking_number"]
            and email.get("status") not in {"delivered","archive"}
        ]
        
        print(f"Tracking {len(shipments)} shipments.")
        
        if not shipments:
            print("No packages to track.")
            return []

        # Initiate tracking request
        response = requests.post(
            tracking_url, json={"apiKey": api_key, "shipments": shipments}
        )
        
        if response.status_code == 200:
            
            json_response = response.json()
            # Check for shipments in the initial response
            cached_shipments = []
            if "shipments" in json_response:
                cached_shipments = json_response.get("shipments", [])
            # Get UUID from response
            uuid = response.json().get("uuid")
            
            polled_shipments = []
            if uuid:

                # Poll tracking status using UUID
                def poll_tracking_status():
                    while True:
                        status_response = requests.get(tracking_url, params={"uuid": uuid, "apiKey": api_key})
                        if status_response.status_code == 200:
                            status_data = status_response.json()

                            # Check if all tracking is done
                            if status_data.get("done", False):
                                return status_data.get("shipments", [])
                            else:
                                print("Tracking in progress... Retrying in 10 seconds.")
                                time.sleep(10)
                        else:
                            print(f"Error polling tracking status: {status_response.text}")
                            break
                    return []

                # Fetch the shipments from polling
                polled_shipments = poll_tracking_status()

            for shipment in cached_shipments + polled_shipments:
                tracking_number = shipment.get("trackingId")
                status = shipment.get("status", "Unknown")
                delivered_by = shipment.get("delivered_by", None)

                # Update the corresponding email by order_number
                for email in emails:
                    if email.get("tracking_number") == tracking_number:
                        email["status"] = status
                        email["delivered_by"] = delivered_by
                        
                        if status.lower() == "pickup": 
                            generate_barcode(tracking_number)
                            emailer.send_email( "Package ready for pickup", 
                                                f"Package with tracking number {tracking_number} is ready for pickup", 
                                                "97cweb@gmail.com",
                                                tracking_number = tracking_number
                                                )
                        
                        # Check if status changed to delivered
                        if status.lower() == "delivered" and email not in delivered_packages:
                            emailer.send_email("Package Delivered", f"Package with tracking number {tracking_number} has been delivered", "97cweb@gmail.com")
                            print(f"Package {tracking_number} marked as delivered.")


        # Save updated emails back to the JSON file
        updated_emails = list(email_lookup.values())
        with open("emails.json", "w", encoding="utf-8") as file:
            json.dump(updated_emails, file, indent=4) 


    except Exception as e:
        print(f"Error checking package status: {e}")


def filter_and_save_tracking_emails(input_file, output_file):
    """
    Filters emails with valid tracking numbers and undelivered statuses.
    Saves the filtered emails to a new file for tracking purposes.
    """
    try:
        with open(input_file, "r", encoding="utf-8") as file:
            emails = json.load(file)

        # Filter emails based on tracking number and undelivered status
        filtered_emails = [
            email for email in emails
            if str(email.get("status", "")).lower() not in {"delivered", "archive"}
        ]

        # Save the filtered emails to the output file
        with open(output_file, "w", encoding="utf-8") as file:
            json.dump(filtered_emails, file, indent=4)
        
        print(f"Filtered {len(filtered_emails)} emails for tracking and saved to {output_file}.")
    except Exception as e:
        print(f"Error filtering and saving tracking emails: {e}")


def manually_update_delivery_status():
    """
    Interactive terminal command to manually update delivery status.
    Goes through each email in emails_to_watch.json and updates emails.json.
    """
    try:
        # Load emails to watch
        with open("emails_to_watch.json", "r", encoding="utf-8") as file:
            emails_to_watch = json.load(file)

        # Load existing emails
        with open("emails.json", "r", encoding="utf-8") as file:
            emails = json.load(file)

        # Create a lookup dictionary for emails by order_number
        email_dict = {email.get("order_number"): email for email in emails if "order_number" in email}
        
        updated_emails_to_watch = []
        
        # Iterate through emails to watch
        for email in emails_to_watch:
            order_number = email.get("order_number")
            tracking_number = email.get("tracking_number", "N/A")
            latest_event = email.get("latest_event", {}).get("status", "No recent events")
            subject = email.get("subject", "No subject")
            sender = email.get("from", "No from available")
            
            print(f"Order Number: {order_number}")
            print(f"Tracking Number: {tracking_number}")
            print(f"Latest Event: {latest_event}")
            print(f"Subject: {subject}")
            print(f"from: {sender}")
            print("=" * 50)
            delivered = input("Is this package delivered? (y/n): ").strip().lower()

            if delivered == "y":
                # Update status to delivered
                if order_number in email_dict:
                    email_dict[order_number]["status"] = "Delivered"
                    print(f"Marked order {order_number} as delivered.")
                    
                    
                    # Also update the email in emails_to_watch.json
                    email["status"] = "delivered"
                else:
                    print(f"Order number {order_number} not found in emails.json.")
            elif delivered == "n":
                print(f"Order {order_number} not marked as delivered.")
            else:
                print("Invalid input. Skipping...")
                
            # Append to updated list of emails to watch if not delivered
            if str(email.get("status", "")).lower() != "delivered":
                updated_emails_to_watch.append(email)

        # Save updated emails back to emails.json
        with open("emails.json", "w", encoding="utf-8") as file:
            json.dump(list(email_dict.values()), file, indent=4)
        print("Emails updated successfully.")
        
        # Save updated emails to watch back to emails_to_watch.json
        with open("emails_to_watch.json", "w", encoding="utf-8") as file:
            json.dump(updated_emails_to_watch, file, indent=4)
        print("Emails_to_watch.json updated successfully.")

    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("Make sure 'emails_to_watch.json' and 'emails.json' exist.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

    

      
# Run the email fetching and processing
fetch_and_save_email_ids(folder="\"Online Purchases\"", scan_all=False)

# Create the OpenAI client for processing
_, _, openai_org, openai_project, api_key, _,_ = read_credentials("secrets.txt")
openai_client = OpenAI(organization=openai_org, project=openai_project, api_key=api_key)

process_and_save_emails(openai_client, folder="\"Online Purchases\"")

_, _, _, _, _, parcel_key,postal_code = read_credentials("secrets.txt")
update_package_status(parcel_key,postal_code)

filter_and_save_tracking_emails("emails.json", "emails_to_watch.json")

#manually_update_delivery_status()

