from fastapi import FastAPI, Request, Form, UploadFile, File, Depends, HTTPException, Response, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import sqlite3
import csv
import os
import io
from typing import List
from typing import Optional
from starlette.middleware.sessions import SessionMiddleware
from database_utils import restore_db, backup_db, get_db_connection, DB_PATH
from datetime import datetime, timedelta, timezone
from drive_uploader import upload_to_drive
from drive_uploader import restore_from_drive
from database_utils import mark_bills_as_paid, cancel_bills_payment, ensure_payment_timestamp_column
from database_utils import get_daily_payment_summary, get_bills_by_date, ensure_receipt_no_column_exists

app = FastAPI()

# Add SessionMiddleware to handle session management
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", "default-secret"),  # Replace with a secure key
    session_cookie="session",
    same_site="lax",
    max_age=86400  # Set the session expiration time (in seconds)
)

# Mount static files directory (for CSS/JS images)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Set up templates directory for HTML rendering
templates = Jinja2Templates(directory="app/templates")

# Session management: Helper to set and check cookies manually
def set_admin_cookie(response: Response):
    expires = datetime.utcnow().replace(tzinfo=timezone.utc) + timedelta(days=7)  # Explicitly setting UTC timezone
    response.set_cookie("admin_logged_in", "true", expires=expires)

def check_admin_logged_in(request: Request):
    if request.cookies.get("admin_logged_in") != "true":
        raise HTTPException(status_code=307, detail="Redirecting to login", headers={"Location": "/admin/login"})


# Database restore and backup functions at startup and shutdown events
@app.on_event("startup")
def startup_event():
    restore_db()

@app.on_event("shutdown")
async def on_shutdown():
    print("Shutting down app... Backing up database.")
    backup_db()

# Test DB connection to ensure it's working
def test_db_connection():
    try:
        conn = sqlite3.connect(DB_PATH)
        print(f"Successfully connected to {DB_PATH}")
        conn.close()
    except sqlite3.OperationalError as e:
        print(f"Error connecting to database: {e}")

test_db_connection()

# Admin login required check (use this in routes you want to protect)
def admin_required(request: Request):
    if not request.session.get("admin_logged_in"):
        raise HTTPException(status_code=307, detail="Redirecting to login", headers={"Location": "/admin/login"})
    return True

# Admin login route
@app.post("/admin/login")
async def login(request: Request, password: str = Form(...)):
    correct_password = os.getenv("ADMIN_PASSWORD")

    if password == correct_password:
        response = RedirectResponse(url="/admin", status_code=303)
        set_admin_cookie(response)  # Set cookie on successful login
        return response
    
    return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid password"})

# Admin login page route
@app.get("/admin/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

# Admin logout route (clear cookie and upload database)
@app.get("/admin/logout")
async def admin_logout(request: Request):
    try:
        # Upload bills.db to Google Drive as bills_backup.db
        upload_to_drive(DB_PATH, "bills_backup.db")
        print("✅ Database uploaded to Google Drive on logout.")
    except Exception as e:
        print(f"⚠️ Failed to upload to Google Drive: {e}")

    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie("admin_logged_in")  # Delete cookie on logout
    return response


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, unpaid_only: Optional[str] = Query(None)):
    check_admin_logged_in(request)
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row

    unpaid_only_flag = unpaid_only == "true"

    summary = conn.execute("""
        SELECT user_name, user_id, SUM(bill_amount) AS total_unpaid, COUNT(user_id) AS unpaid_count
        FROM bills 
        WHERE paid = 0 
        GROUP BY user_id
    """).fetchall()

    if unpaid_only_flag:
        bills = conn.execute("SELECT * FROM bills WHERE paid = 0 ORDER BY user_id, pay_period DESC").fetchall()
    else:
        bills = conn.execute("SELECT * FROM bills ORDER BY user_id, pay_period DESC").fetchall()

    conn.close()

    total_unpaid = sum(row['total_unpaid'] for row in summary)

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "summary": summary,
        "bills": bills,
        "total": total_unpaid,
        "unpaid_only": unpaid_only_flag
    })



# Admin restore db from google drive (if necessary)
@app.post("/admin/restore")
async def restore_db_route():
    success = restore_from_drive()
    return {
        "success": success,
        "message": "✅ Database restored" if success else "❌ Restore failed"
    }


# Admin update bills route
@app.post("/admin/update_payment")
async def update_payment_route(
    request: Request,
    bill_ids: Optional[List[int]] = Form(None)
):
    check_admin_logged_in(request)
    if bill_ids:
        mark_bills_as_paid(bill_ids)
    return RedirectResponse("/admin", status_code=303)



@app.post("/admin/update_payment_through_cart")
async def update_payment_through_cart(request: Request, bill_ids: List[int] = Form(...)):
    try:
        conn = get_db_connection()
        for bill_id in bill_ids:
            # Mark the bills as paid in the database
            conn.execute("UPDATE bills SET paid = 1 WHERE id = ?", (bill_id,))
        conn.commit()
        conn.close()
        # /admin/update_payment_through_cart
        # After marking bills as paid:
        return RedirectResponse(
            url=f"/admin/shopping_cart?receipt_ids={','.join(map(str, bill_ids))}",
            status_code=303
        )

    except Exception as e:
        print(f"⚠️ Error processing payment: {e}")
        return {"error": "There was an issue processing the payment."}



@app.get("/admin/shopping_cart", response_class=HTMLResponse)
async def shopping_cart(request: Request, receipt_ids: Optional[str] = Query(None)):
    check_admin_logged_in(request)
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row

    receipt_id_list = []
    selected_bills = []
    all_unpaid_bills = []

    if receipt_ids:
        receipt_id_list = [int(i) for i in receipt_ids.split(",") if i.isdigit()]
        placeholders = ",".join(["?"] * len(receipt_id_list))
        selected_bills = conn.execute(
            f"SELECT * FROM bills WHERE id IN ({placeholders})",
            receipt_id_list
        ).fetchall()

    # Load all unpaid bills for selection (excluding already selected ones)
    if receipt_id_list:
        placeholders = ",".join(["?"] * len(receipt_id_list))
        all_unpaid_bills = conn.execute(
            f"SELECT * FROM bills WHERE paid = 0 AND id NOT IN ({placeholders})",
            receipt_id_list
        ).fetchall()
    else:
        all_unpaid_bills = conn.execute("SELECT * FROM bills WHERE paid = 0").fetchall()

    conn.close()

    return templates.TemplateResponse("shopping_cart.html", {
        "request": request,
        "selected_bills": selected_bills,
        "receipt_ids": receipt_id_list,
        "all_unpaid_bills": all_unpaid_bills,
    })





@app.post("/admin/cancel_payment")
async def cancel_payment_route(
    request: Request,
    bill_ids_cancel: Optional[List[int]] = Form(None)
):
    check_admin_logged_in(request)
    if bill_ids_cancel:
        cancel_bills_payment(bill_ids_cancel)
    return RedirectResponse("/admin", status_code=303)


# Public user view page
@app.get("/", response_class=HTMLResponse)
async def public_view(request: Request):
    return templates.TemplateResponse("user.html", {"request": request})

# User-specific bills page
@app.get("/user", response_class=HTMLResponse)
async def user_view(request: Request, user_id: str):
    conn = get_db_connection()
    c = conn.cursor()

    try:
        c.execute("SELECT * FROM bills WHERE user_id = ? AND paid = 0", (user_id,))
        user_data = c.fetchall()

        return templates.TemplateResponse("user.html", {
            "request": request,
            "user_id": user_id,
            "user_data": user_data
        })

    except sqlite3.Error as e:
        return templates.TemplateResponse("user.html", {
            "request": request,
            "user_id": user_id,
            "user_data": [],
            "error": f"Database error: {str(e)}"
        })

    finally:
        conn.close()

# ====upload csv route
@app.post("/admin/upload")
async def upload_csv(request: Request, csv_file: UploadFile = File(...)):
    check_admin_logged_in(request)
    conn = get_db_connection()
    cursor = conn.cursor()
    contents = await csv_file.read()

    decoded = contents.decode("utf-8")
    raw_reader = csv.DictReader(io.StringIO(decoded))

    # Header mapping: CSV header → expected DB column name
    csv_to_db_keys = {
        'lvl1_cost': 'lv1_cost',
        'lvl2_cost': 'lv2_cost',
        'lvl3_cost': 'lv3_cost',
        'lvl4_cost': 'lv4_cost',
        'user_id': 'user_id',
        'device_id': 'device_id',
        'user_name': 'user_name',
        'user_address': 'user_address',
        'pay_period': 'pay_period',
        'meter_past': 'meter_past',
        'meter_now': 'meter_now',
        'usage': 'usage',
        'basic_cost': 'basic_cost',
        'bill_amount': 'bill_amount'
    }

    inserted_count = 0
    for raw_row in raw_reader:
        try:
            # Remap keys using defined mapping
            row = {}
            for csv_key, db_key in csv_to_db_keys.items():
                if csv_key in raw_row:
                    row[db_key] = raw_row[csv_key].strip()
                else:
                    row[db_key] = ""

            user_id = row['user_id']
            pay_period = row['pay_period']

            # Check for duplicate
            cursor.execute("SELECT 1 FROM bills WHERE user_id = ? AND pay_period = ?", (user_id, pay_period))
            if cursor.fetchone():
                print(f"⚠️ Skipping duplicate: user_id={user_id}, pay_period={pay_period}")
                continue

            # === Cleaning Functions ===
            def clean_int(val):
                val = val.replace('$', '').replace(',', '').strip()
                return int(float(val or 0))

            def clean_float(val):
                val = val.replace('$', '').replace(',', '').strip()
                return round(float(val or 0.0), 2)

            def clean_date_to_mmdd(val):
                try:
                    dt = datetime.strptime(val.strip(), "%m/%d/%Y")
                    return dt.strftime("%m/%d")
                except:
                    return val.strip()

            # === Clean fields ===
            meter_past = clean_int(row['meter_past'])
            meter_now = clean_int(row['meter_now'])
            usage = clean_int(row['usage'])
            lv1_cost = clean_float(row['lv1_cost'])
            lv2_cost = clean_float(row['lv2_cost'])
            lv3_cost = clean_float(row['lv3_cost'])
            lv4_cost = clean_float(row['lv4_cost'])
            basic_cost = clean_float(row['basic_cost'])
            bill_amount = clean_float(row['bill_amount'])
            user_address = clean_date_to_mmdd(row['user_address'])

            # === Insert into DB ===
            cursor.execute("""
                INSERT INTO bills (
                    user_id, device_id, user_name, user_address, pay_period, meter_past, meter_now,
                    usage, lv1_cost, lv2_cost, lv3_cost, lv4_cost, basic_cost, bill_amount, paid
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (
                user_id, row['device_id'], row['user_name'], user_address, pay_period,
                meter_past, meter_now, usage,
                lv1_cost, lv2_cost, lv3_cost, lv4_cost,
                basic_cost, bill_amount
            ))

            inserted_count += 1

        except Exception as e:
            print(f"❌ Skipped row due to error: {e}")
            continue

    conn.commit()
    conn.close()

    ensure_payment_timestamp_column()
    ensure_receipt_no_column_exists()
    print(f"✅ Inserted {inserted_count} new rows from {csv_file.filename}")
    backup_db()

    return RedirectResponse(url="/admin", status_code=303)



# Admin invoice route (view and print invoices)
@app.get("/admin/invoice/{user_id}", response_class=HTMLResponse)
async def invoice(request: Request, user_id: str):
    check_admin_logged_in(request)  # Ensure admin is logged in
    conn = get_db_connection()
    c = conn.cursor()

    try:
        c.execute("SELECT * FROM bills WHERE user_id = ? AND paid = 0", (user_id,))
        user_data = c.fetchall()

        return templates.TemplateResponse("invoice.html", {
            "request": request,
            "user_id": user_id,
            "user_data": user_data
        })

    except sqlite3.Error as e:
        return templates.TemplateResponse("invoice.html", {
            "request": request,
            "user_id": user_id,
            "user_data": [],
            "error": f"Database error: {str(e)}"
        })

    finally:
        conn.close()


# receipt of paid bill
@app.get("/admin/receipt/{bill_id}", response_class=HTMLResponse)
def show_invoice(request: Request, bill_id: int):
    check_admin_logged_in(request)  # Ensure admin is logged in
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bills WHERE id = ?", (bill_id,))
    bill = cursor.fetchone()
    conn.close()

    if not bill:
        return HTMLResponse("<h2>Receipt not found.</h2>", status_code=404)

    return templates.TemplateResponse("receipt.html", {"request": request, "bill": bill})


# payment summary route
@app.get("/admin/payment_summary", response_class=HTMLResponse)
async def payment_summary(request: Request, start: Optional[str] = Query(None), end: Optional[str] = Query(None), date: Optional[str] = Query(None)):
    check_admin_logged_in(request)

    if date:
        bills = get_bills_by_date(date)
        total = sum(b["bill_amount"] for b in bills)
        return templates.TemplateResponse("payment_summary.html", {
            "request": request,
            "mode": "daily_details",
            "selected_date": date,
            "bills": bills,
            "subtotal": total
        })
    else:
        summary = get_daily_payment_summary(start, end)
        return templates.TemplateResponse("payment_summary.html", {
            "request": request,
            "mode": "summary",
            "summary": summary,
            "start": start,
            "end": end
        })

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
