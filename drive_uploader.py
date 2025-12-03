# drive_uploader.py

import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.http import MediaIoBaseDownload
from database_utils import DB_PATH, ensure_payment_timestamp_column, ensure_receipt_no_column_exists

# Load credentials from Railway environment variable
service_account_info = json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT'])
creds = service_account.Credentials.from_service_account_info(
    service_account_info,
    scopes=["https://www.googleapis.com/auth/drive"]
)

# Hardcoded shared Google Drive folder ID
FOLDER_ID = '1cC4D1oNqRHh-Y4v3RiI8iLmLTMyrO8Us'

# In drive_uploader.py

def upload_to_drive(file_path, file_name):
    try:
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

        file_id = uploaded_file.get('id')
        print(f"✅ Uploaded to Google Drive with file ID: {file_id}")
        
        # 🟢 CRITICAL FIX: Explicitly return True on success
        return True 

    except Exception as e:
        # Catch any API errors, file errors, etc., and print a detailed error
        print(f"❌ Upload failed for {file_name}. Error: {e}")
        return False # 🔴 Explicitly return False on failure



def restore_from_drive():
    service = build('drive', 'v3', credentials=creds)

    folder_id = FOLDER_ID

    # Search for files starting with 'bills_backup' in the given folder
    query = f"name contains 'bills_backup' and '{folder_id}' in parents and trashed = false"
    response = service.files().list(
        q=query,
        spaces='drive',
        fields='files(id, name, createdTime)',
        orderBy='createdTime desc',
        pageSize=1
    ).execute()

    files = response.get('files', [])

    if not files:
        print("❌ No backup files found in Google Drive.")
        return False

    latest_file = files[0]
    file_id = latest_file['id']
    file_name = latest_file['name']

    print(f"📦 Restoring latest backup: {file_name}")

    request = service.files().get_media(fileId=file_id)

    with open(DB_PATH, 'wb') as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            print(f"⬇️ Download progress: {int(status.progress() * 100)}%")

    ensure_payment_timestamp_column()
    ensure_receipt_no_column_exists()
    print(f"✅ Restored database from Google Drive backup ({file_name}) to {DB_PATH}")
    return True

