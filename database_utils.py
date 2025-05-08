import os
import sqlite3
import shutil
import glob
import csv
from datetime import datetime
from typing import Optional, List, Dict
import uuid

DB_PATH = "app/db/bills.db"
BACKUP_DIR = "backups"

def ensure_backup_folder():
    os.makedirs(BACKUP_DIR, exist_ok=True)

def ensure_payment_timestamp_column():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if payment_timestamp column exists
    cursor.execute("PRAGMA table_info(bills)")
    columns = [col["name"] for col in cursor.fetchall()]
    if "payment_timestamp" not in columns:
        cursor.execute("ALTER TABLE bills ADD COLUMN payment_timestamp TEXT")
        conn.commit()
        print("🛠️ Added 'payment_timestamp' column to bills table.")

    conn.close()

def ensure_receipt_no_column_exists():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if 'receipt_no' column already exists
    cursor.execute("PRAGMA table_info(bills);")
    columns = [row[1] for row in cursor.fetchall()]
    
    if 'receipt_no' not in columns:
        cursor.execute("ALTER TABLE bills ADD COLUMN receipt_no TEXT;")
        conn.commit()

    conn.close()



def generate_receipt_no(bill_id):
    now = datetime.now()
    return f"RCP-{now.strftime('%Y%m%d')}-{bill_id}-{uuid.uuid4().hex[:4]}"
    
def mark_bills_as_paid(bill_ids: list[int]):
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for bill_id in bill_ids:
        cursor.execute("SELECT paid, receipt_no FROM bills WHERE id = ?", (bill_id,))
        row = cursor.fetchone()
        if row and not row['paid']:  # Only update unpaid bills
            receipt_no = generate_receipt_no(bill_id)
            cursor.execute("""
                UPDATE bills 
                SET paid = 1, payment_timestamp = ?, receipt_no = ?
                WHERE id = ?
            """, (now, receipt_no, bill_id))

    conn.commit()
    conn.close()


def cancel_bills_payment(bill_ids_cancel: list[int]):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.executemany("UPDATE bills SET paid = 0, payment_timestamp = NULL, receipt_no = NULL WHERE id = ?", [(bill_id,) for bill_id in bill_ids_cancel])
    conn.commit()
    conn.close()



def backup_db():
    ensure_backup_folder()

    if not os.path.exists(DB_PATH):
        print("⚠️ No database found to back up.")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    backup_filename = f"bills_backup_{timestamp}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_filename)

    shutil.copy2(DB_PATH, backup_path)
    print(f"✅ Backup created at: {backup_path}")


def restore_db():
    ensure_backup_folder()

    # Get sorted list of backup files from relative BACKUP_DIR
    backups = sorted(
        glob.glob(os.path.join(BACKUP_DIR, "bills_backup_*.db")),
        reverse=True
    )

    # Restore the most recent backup if available
    if backups:
        latest_backup = backups[0]
        shutil.copyfile(latest_backup, DB_PATH)
        print(f"✅ Database restored from: {latest_backup}")
    else:
        print("⚠️ No backups found. Starting with a fresh database.")

    # Ensure the table structure is present (fresh DB or restored one)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            device_id TEXT,
            user_name TEXT,
            user_address TEXT,
            pay_period TEXT,
            meter_past INTEGER,
            meter_now INTEGER,
            usage INTEGER,
            lv1_cost REAL,
            lv2_cost REAL,
            lv3_cost REAL,
            lv4_cost REAL,
            basic_cost REAL,
            bill_amount REAL,
            paid INTEGER DEFAULT 0
        )
    """)

    ensure_payment_timestamp_column()
    ensure_receipt_no_column_exists()
    
    conn.commit()
    conn.close()


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
    
    ensure_payment_timestamp_column()
    ensure_receipt_no_column_exists()
    backup_db()
    print(f"✅ Inserted {rows_inserted} rows and created backup.")


#===payment summary====
def get_daily_payment_summary(start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict]:
    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
        SELECT DATE(payment_timestamp) as payment_date, SUM(bill_amount) as total_payment
        FROM bills
        WHERE paid = 1
    """
    params = []

    if start_date:
        query += " AND DATE(payment_timestamp) >= ?"
        params.append(start_date)
    if end_date:
        query += " AND DATE(payment_timestamp) <= ?"
        params.append(end_date)

    query += " GROUP BY DATE(payment_timestamp) ORDER BY DATE(payment_timestamp) DESC"
    cursor.execute(query, params)
    result = [{"payment_date": row[0], "total_payment": row[1]} for row in cursor.fetchall()]
    conn.close()
    return result


def get_bills_by_date(payment_date: str) -> List[Dict]:
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT user_name, pay_period, bill_amount
        FROM bills
        WHERE paid = 1 AND DATE(payment_timestamp) = ?
        ORDER BY user_name
    """, (payment_date,))
    
    result = [{"user_name": row[0], "pay_period": row[1], "bill_amount": row[2]} for row in cursor.fetchall()]
    conn.close()
    return result
