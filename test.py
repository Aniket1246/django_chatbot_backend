# test_service_account_email.py
import json
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build

BASE_DIR = Path(__file__).resolve().parent
credentials_path = BASE_DIR / "credsam.json"

try:
    print("Loading credentials...")
    with open(credentials_path, 'r') as f:
        cred_data = json.load(f)
        service_account_email = cred_data.get('client_email')
    
    print(f"Service Account Email: {service_account_email}")

    print("Creating service...")
    SCOPES = ["https://www.googleapis.com/auth/calendar"]
    credentials = service_account.Credentials.from_service_account_file(
        str(credentials_path), scopes=SCOPES
    )
    service = build("calendar", "v3", credentials=credentials)

    print("Testing calendar list access...")
    calendar_list = service.calendarList().list().execute()
    print(f"✅ Successfully accessed calendar list")
    print(f"Found {len(calendar_list.get('items', []))} calendars")
    
    # Print all available calendars
    for cal in calendar_list.get('items', []):
        print(f"  - {cal['summary']} ({cal['id']}) - Access: {cal.get('accessRole', 'unknown')}")
    
    # Try to access the service account's email as calendar ID
    print(f"\nTesting service account email as calendar ID...")
    calendar = service.calendarList().get(calendarId=service_account_email).execute()
    print(f"✅ Successfully accessed service account email calendar")
    print(f"Calendar ID: {calendar.get('id')}")
    print(f"Calendar Name: {calendar.get('summary')}")
    
    # Try creating a test event
    print("\nTesting event creation...")
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    
    UK_TZ = ZoneInfo("Europe/London")
    start_time = datetime.now(UK_TZ) + timedelta(hours=1)
    end_time = start_time + timedelta(minutes=15)
    
    event = {
        'summary': 'Test Mentorship Session',
        'description': 'This is a test mentorship session',
        'start': {
            'dateTime': start_time.isoformat(),
            'timeZone': 'Europe/London',
        },
        'end': {
            'dateTime': end_time.isoformat(),
            'timeZone': 'Europe/London',
        },
        'attendees': [
            {'email': 'kapilsanjaykanjani@gmail.com'},
            {'email': 'test@example.com'}
        ],
        'location': 'Google Meet - https://meet.google.com/test-link'
    }
    
    created_event = service.events().insert(calendarId=service_account_email, body=event, sendUpdates='all').execute()
    print(f"✅ Successfully created test event: {created_event.get('htmlLink')}")
    print(f"Event ID: {created_event.get('id')}")
    
    # Clean up - delete the test event
    service.events().delete(calendarId=service_account_email, eventId=created_event.get('id')).execute()
    print(f"✅ Successfully deleted test event")
    
    print("\n🎉 All tests passed!")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()