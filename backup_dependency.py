from fastapi import BackgroundTasks, Depends
# Import your existing upload function
from drive_uploader import upload_to_drive
from database_utils import DB_PATH
import os
from pathlib import Path

# --- Configuration ---

DRIVE_FILENAME = "bills_backup.db"


# 1. Internal Task Execution Function
def _perform_background_backup():
    """Internal function that executes the backup and handles logging/errors."""
    try:
        print(f"⏳ Background task: Searching for DB at path: {DB_PATH}") # 👈 Add this line
        
        # Call your existing function
        file_id = upload_to_drive(DB_PATH, DRIVE_FILENAME)
        
        if file_id:
            print("✅ Background DB backup completed successfully.")
        else:
            # If upload_to_drive returns False, log it
            print("❌ Background DB backup failed (Function returned False).")

    except Exception as e:
        # ⚠️ CRITICAL CHANGE: Catch ALL exceptions here.
        # This prevents the ASGI application from seeing the error and logging the traceback.
        print(f"❌ CRITICAL BACKGROUND ERROR: Database upload failed due to uncaught exception: {type(e).__name__}: {e}")
        # Optionally, log the traceback to a dedicated log file if necessary.
        # This keeps the main application logs clean.


# 2. The FastAPI Dependency (The Queuer)
def queue_backup_on_write(background_tasks: BackgroundTasks):
    """
    FastAPI dependency function that queues the backup task.
    """
    print("🔔 Triggering non-blocking backup...")
    # Add the execution function to the queue
    background_tasks.add_task(_perform_background_backup)
    
    # The dependency returns None, fulfilling the Dependency Injection requirement
    return None

# 3. Create the reusable dependency object
BackupOnWrite = Depends(queue_backup_on_write)
