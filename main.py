from fastapi import FastAPI, Request, Form, UploadFile, File, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import sqlite3
import csv
import os
import io
from typing import List
from starlette.middleware.sessions import SessionMiddleware
from database_utils import restore_db, backup_db, get_db_connection, DB_PATH
from datetime import datetime, timedelta, timezone


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

# Admin logout route (clear cookie)
@app.get("/admin/logout")
async def admin_logout(request: Request):
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie("admin_logged_in")  # Delete cookie on logout
    return response

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    check_admin_logged_in(request)  # Check if admin is logged in
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row

    summary = conn.execute("""
        SELECT user_name, user_id, SUM(bill_amount) 
        FROM bills 
        WHERE paid = 0 
        GROUP BY user_id
    """).fetchall()

    bills = conn.execute("SELECT * FROM bills ORDER BY user_id, pay_period DESC").fetchall()
    conn.close()

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "summary": summary,
        "bills": bills
    })


# Admin update bills route
@app.post("/admin/update")
async def update_bills(request: Request, bill_ids: list[int] = Form(...)):
    check_admin_logged_in(request)  # Ensure admin is logged in
    
    conn = get_db_connection()
    cursor = conn.cursor()

    # Update logic
    for bill_id in bill_ids:
        cursor.execute("UPDATE bills SET paid = 1 WHERE id = ?", (bill_id,))
    
    conn.commit()
    conn.close()

    return RedirectResponse(url="/admin", status_code=303)


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

@app.post("/admin/upload")
async def upload_csv(request: Request, csv_file: UploadFile = File(...)):
    check_admin_logged_in(request)
    conn = get_db_connection()
    cursor = conn.cursor()
    contents = await csv_file.read()

    decoded = contents.decode("utf-8")
    reader = csv.DictReader(io.StringIO(decoded))

    inserted_count = 0
    skipped_count = 0
    for row in reader:
        try:
            # Check if a bill with same user_id and pay_period already exists
            cursor.execute("SELECT 1 FROM bills WHERE user_id = ? AND pay_period = ?", (row['user_id'], row['pay_period']))
            if cursor.fetchone():
                print(f"⚠️ Skipped duplicate: user_id={row['user_id']} pay_period={row['pay_period']}")
                skipped_count += 1
                continue

            cursor.execute("""
                INSERT INTO bills (
                    user_id, device_id, user_name, user_address, pay_period,
                    meter_past, meter_now, usage,
                    lv1_cost, lv2_cost, lv3_cost, lv4_cost,
                    basic_cost, bill_amount, paid
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (
                row['user_id'], row['device_id'], row['user_name'], row['user_address'], row['pay_period'],
                float(row['meter_past']), float(row['meter_now']), float(row['usage']),
                float(row['lv1_cost']), float(row['lv2_cost']), float(row['lv3_cost']), float(row['lv4_cost']),
                float(row['basic_cost']), float(row['bill_amount'])
            ))
            inserted_count += 1

        except Exception as e:
            print(f"❌ Error inserting row: {e}")
            continue

    conn.commit()
    conn.close()
    backup_db()

    print(f"✅ Inserted: {inserted_count}, ⚠️ Skipped duplicates: {skipped_count} from {csv_file.filename}")
    return RedirectResponse(url="/admin", status_code=303)


# Admin update bills (mark bills as paid)
@app.post("/admin/update")
async def update_bills(request: Request, bill_ids: List[int] = Form(...), _=Depends(admin_required)):
    check_admin_logged_in(request)  # Ensure admin is logged in
    conn = get_db_connection()
    cursor = conn.cursor()
    for bill_id in bill_ids:
        cursor.execute("UPDATE bills SET paid = 1 WHERE id = ?", (bill_id,))
    conn.commit()
    conn.close()

    backup_db()

    return RedirectResponse(url="/admin", status_code=303)

# Admin invoice route (view and print invoices)
@app.get("/admin/invoice/{user_id}", response_class=HTMLResponse)
async def invoice(request: Request, user_id: str, _=Depends(admin_required)):
    check_admin_logged_in(request)  # Ensure admin is logged in
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM bills WHERE user_id = ? AND paid = 0", (user_id,)).fetchall()
    conn.close()
    return templates.TemplateResponse("invoice.html", {"request": request, "bills": rows})

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
