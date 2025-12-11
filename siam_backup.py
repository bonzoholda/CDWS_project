import os
import subprocess
import shutil # For cleaning up directories if needed

# --- IMPORT YOUR EXISTING MODULE ---
# Assuming 'drive_uploader.py' is in a place accessible by Python's path.
# If it's in a different directory, you might need to adjust the path or import structure.
# For simplicity, we assume it's in the same project root or a sub-folder already in the path.

try:
    # ----------------------------------------------------------------------
    # IMPORTANT: Ensure this import statement matches the location of your file
    # If drive_uploader.py is in the same directory, this is perfect:
    from drive_uploader import upload_to_drive_siam 
    # ----------------------------------------------------------------------
except ImportError:
    print("ERROR: Could not import 'upload_to_drive' from 'drive_uploader.py'.")
    print("Please ensure the file is in the correct directory or the path is set.")
    # Exit or raise an error if the import fails to prevent execution.
    raise


# --- Configuration ---
# 1. The local file you want to compress and upload
SOURCE_FILE_PATH = "C:\SIAM-HB\LocalData\KonsumenCenter_Ver2013_be.accdb" # Example: database file
# 2. The output name for the compressed file
ARCHIVE_FILENAME = "KonsumenCenter_Ver2013_be.7z"
# 3. The path where the temporary .7z file will be created
TEMP_OUTPUT_PATH = os.path.join(os.getcwd(), ARCHIVE_FILENAME)
# 4. Google Drive folder ID to upload to (If your function needs it for placement)
# NOTE: If your upload_to_drive function handles the folder ID internally, 
# you might not need this line in the main script.
# GOOGLE_DRIVE_FOLDER_ID = "YOUR_GOOGLE_DRIVE_FOLDER_ID" 
# --- End Configuration ---


def compress_file_with_7zip(source_path, output_path):
    """
    Compresses a local file into the .7z format using the 7z command-line tool.
    (Keeping this function from the previous script as it is essential for .7z)
    """
    print(f"Compressing {source_path} to {output_path}...")
    try:
        # Use a list for the command for safety
        command = ['7z', 'a', '-mx9', output_path, source_path]
        
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True # Raise exception on non-zero exit code
        )
        print("Compression successful.")
        return True
    
    except subprocess.CalledProcessError as e:
        print(f"ERROR: 7-Zip compression failed.")
        print(f"Stderr: {e.stderr}")
        print("Please ensure 7-Zip is installed and '7z' command is in your system PATH.")
        return False
    except FileNotFoundError:
        print("ERROR: 7z command not found. Install 7-Zip or adjust the command variable.")
        return False


def main_automation_task():
    """
    The main function to be called when the admin dashboard button is clicked.
    """
    print("--- Starting File Compression and Upload Process ---")
    
    # 1. Check if the source file exists
    if not os.path.exists(SOURCE_FILE_PATH):
        print(f"ERROR: Source file not found: {SOURCE_FILE_PATH}")
        return

    # 2. Compress the file
    compression_success = compress_file_with_7zip(SOURCE_FILE_PATH, TEMP_OUTPUT_PATH)
    if not compression_success:
        return
        
    try:
        # 3. Use your existing, imported Google Drive upload function!
        print(f"Calling existing upload function: upload_to_drive('{TEMP_OUTPUT_PATH}', '{ARCHIVE_FILENAME}')")
        
        # NOTE: Adjust the arguments below if your function requires the folder ID.
        # Example if your function requires the folder ID:
        # upload_success = upload_to_drive(TEMP_OUTPUT_PATH, ARCHIVE_FILENAME, GOOGLE_DRIVE_FOLDER_ID)
        
        # Calling your function with the newly compressed file path and name
        upload_success = upload_to_drive(TEMP_OUTPUT_PATH, ARCHIVE_FILENAME) 
        
        if upload_success:
            print("--- Automation Task Completed Successfully ---")
        else:
            print("--- Automation Task Failed During Upload (Check drive_uploader.py logs) ---")

    finally:
        # 4. Cleanup: Delete the temporary compressed file
        if os.path.exists(TEMP_OUTPUT_PATH):
            os.remove(TEMP_OUTPUT_PATH)
            print(f"Cleaned up temporary archive: {ARCHIVE_FILENAME}")


if __name__ == '__main__':
    main_automation_task()
