# drive_uploader.py

import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.http import MediaIoBaseDownload
from database_utils import DB_PATH

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



def restore_from_drive():
    service = build('drive', 'v3', credentials=creds)

    file_name = "bills.db"
    folder_id = FOLDER_ID

    query = f"name='{file_name}' and '{folder_id}' in parents and trashed = false"
    response = service.files().list(q=query, spaces='drive', fields='files(id, name)', pageSize=1).execute()
    files = response.get('files', [])

    if not files:
        print("❌ Backup file not found in Google Drive.")
        return False

    file_id = files[0]['id']
    request = service.files().get_media(fileId=file_id)

    with open(DB_PATH, 'wb') as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            print(f"⬇️ Download progress: {int(status.progress() * 100)}%")

    print(f"✅ Restored database from Google Drive to {DB_PATH}")
    return True

