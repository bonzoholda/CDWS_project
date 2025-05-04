from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import sqlite3
import csv
import os
from typing import List
from starlette.middleware.sessions import SessionMiddleware
from database_utils import restore_db
from database_utils import backup_db
from fastapi import Depends, HTTPException, status

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SECRET_KEY", "default-secret"))
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

@app.on_event("startup")
def startup_event():
    restore_db()

@app.on_event("shutdown")
async def on_shutdown():
    print("Shutting down app... Backing up database.")
    backup_db()

DB_PATH = "app/db/bills.db"

def admin_required(request: Request):
    if not request.session.get("admin_logged_in"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authorized")

@app.get("/admin", dependencies=[Depends(admin_required)])
async def admin_dashboard(request: Request):
    # your existing admin dashboard logic
    return templates.TemplateResponse("admin.html", {"request": request})


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Ensure the bills table exists (safe even if it already exists)
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
    conn.commit()

    return conn



@app.post("/admin/login")
async def login(request: Request, password: str = Form(...)):
    # Get password from environment variable; it must be set in Railway or via environment variables
    correct_password = os.getenv("ADMIN_PASSWORD")
    
    if not correct_password:
        # If no password is set in the environment variables, return an error
        return templates.TemplateResponse("login.html", {"request": request, "error": "Password environment variable is not set!"})

    if password == correct_password:
        request.session["admin_logged_in"] = True
        return RedirectResponse(url="/admin", status_code=303)
    
    return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid password"})

@app.get("/admin/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/admin/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    conn = get_db_connection()
    summary = conn.execute("""
        SELECT user_id, user_name, user_address, SUM(bill_amount)
        FROM bills
        WHERE paid = 0
        GROUP BY user_id
    """).fetchall()

    bills = conn.execute("SELECT * FROM bills").fetchall()
    conn.close()
    return templates.TemplateResponse("admin.html", {"request": request, "summary": summary, "bills": bills})

@app.get("/", response_class=HTMLResponse)
async def public_view(request: Request):
    return templates.TemplateResponse("user.html", {"request": request})

@app.get("/user", response_class=HTMLResponse)
async def user_view(request: Request, user_id: str):
    conn = get_db_connection()
    c = conn.cursor()

    try:
        # Query the bills table for the specific user_id and unpaid bills
        c.execute("SELECT * FROM bills WHERE user_id = ? AND paid = 0", (user_id,))
        user_data = c.fetchall()

        return templates.TemplateResponse("user.html", {
            "request": request,
            "user_id": user_id,
            "user_data": user_data  # must match what the template expects
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
async def upload_csv(csv_file: UploadFile = File(...)):
    conn = get_db_connection()
    cursor = conn.cursor()
    contents = await csv_file.read()
    decoded = contents.decode("utf-8").splitlines()
    reader = csv.DictReader(decoded)

    
        for row in reader:
            cursor.execute("""
                INSERT INTO bills (user_id, device_id, user_name, user_address, pay_period, meter_past, meter_now,
                                   usage, lv1_cost, lv2_cost, lv3_cost, lv4_cost, basic_cost, bill_amount, paid)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (
                row['user_id'], row['device_id'], row['user_name'], row['user_address'], row['pay_period'],
                row['meter_past'], row['meter_now'], row['usage'],
                row['lv1_cost'], row['lv2_cost'], row['lv3_cost'], row['lv4_cost'],
                row['basic_cost'], row['bill_amount']
            ))


    conn.commit()
    conn.close()
    
    backup_db()
    
    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/update")
async def update_bills(request: Request, bill_ids: List[int] = Form(...)):
    conn = get_db_connection()
    cursor = conn.cursor()
    for bill_id in bill_ids:
        cursor.execute("UPDATE bills SET paid = 1 WHERE id = ?", (bill_id,))
    conn.commit()
    conn.close()

    backup_db()

    return RedirectResponse(url="/admin", status_code=303)

@app.get("/admin/invoice/{user_id}", response_class=HTMLResponse)
async def invoice(request: Request, user_id: str):
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM bills WHERE user_id = ? AND paid = 0", (user_id,)).fetchall()
    conn.close()
    return templates.TemplateResponse("invoice.html", {"request": request, "bills": rows})
