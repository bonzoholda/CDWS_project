from fastapi import BackgroundTasks, Depends
# Import your existing upload function
from drive_uploader import upload_to_drive 
import os

# --- Configuration ---
DB_PATH = "bills.db"
DRIVE_FILENAME = "bills_backup.db"


# 1. Internal Task Execution Function
def _perform_background_backup():
    """Executes the core, blocking upload task in a background thread."""
    print("⏳ Background task: Starting database backup to Drive...")
    
    # Call your existing function
    success = upload_to_drive(DB_PATH, DRIVE_FILENAME)
    
    if success:
        print("✅ Background DB backup completed successfully.")
    else:
        # Important: Log the error here, as the user won't see it directly.
        print("❌ Background DB backup failed. Check drive_uploader.py logs.")


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
