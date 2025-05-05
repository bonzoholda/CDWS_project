# drive_uploader.py

import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Load credentials from Railway environment variable
service_account_info = json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT'])
creds = service_account.Credentials.from_service_account_info(
    service_account_info,
    scopes=["https://www.googleapis.com/auth/drive"]
)

# Hardcoded shared Google Drive folder ID
FOLDER_ID = '1cC4D1oNqRHh-Y4v3RiI8iLmLTMyrO8Us'

def upload_to_drive(file_path, file_name):
    service = build('drive', 'v3', credentials=creds)

    file_metadata = {
        'name': file_name,
        'parents': [FOLDER_ID]
    }

    media = MediaFileUpload(file_path, resumable=True)
    uploaded_file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id'
    ).execute()

    print(f"✅ Uploaded to Google Drive with file ID: {uploaded_file.get('id')}")
