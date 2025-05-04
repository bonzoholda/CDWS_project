import os
import sqlite3
import shutil
import glob
import datetime
import csv

DB_PATH = "bills.db"
BACKUP_DIR = "backups"

def ensure_backup_folder():
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)

def backup_db():
    ensure_backup_folder()
    if os.path.exists(DB_PATH):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = os.path.join(BACKUP_DIR, f"bills_backup_{timestamp}.db")
        shutil.copyfile(DB_PATH, backup_file)
        print(f"✅ Backup created at: {backup_file}")
    else:
        print("❌ No database found to back up.")

def restore_db():
    ensure_backup_folder()
    backups = sorted(glob.glob(os.path.join(BACKUP_DIR, "bills_backup_*.db")), reverse=True)
    if backups:
        latest_backup = backups[0]
        shutil.copyfile(latest_backup, DB_PATH)
        print(f"✅ Database restored from: {latest_backup}")
    else:
        print("⚠️ No backups found. Starting with a fresh database.")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Enables dict-like access in templates
    return conn

def insert_from_csv(file_path: str):
    conn = get_db_connection()
    cursor = conn.cursor()

    with open(file_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        rows_inserted = 0
        for row in reader:
            cursor.execute("""
                INSERT INTO bills (
                    user_id, device_id, user_name, user_address,
                    pay_period, meter_past, meter_now, usage,
                    lv1_cost, lv2_cost, lv3_cost, lv4_cost,
                    basic_cost, bill_amount, paid
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (
                row['user_id'], row['device_id'], row['user_name'], row['user_address'],
                row['pay_period'], row['meter_past'], row['meter_now'], row['usage'],
                row['lv1_cost'], row['lv2_cost'], row['lv3_cost'], row['lv4_cost'],
                row['basic_cost'], row['bill_amount']
            ))
            rows_inserted += 1

    conn.commit()
    conn.close()
    backup_db()
    print(f"✅ Inserted {rows_inserted} rows and created backup.")
