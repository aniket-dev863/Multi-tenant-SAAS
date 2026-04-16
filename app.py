from burn_rate import run_analysis_and_alert, calculate_burn_rates
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
import boto3
import json 
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from bson.objectid import ObjectId
import os
import psycopg2
import psycopg2.extras
from pymongo import MongoClient
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

load_dotenv()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


app = Flask(__name__)
secret_key = os.getenv("SECRET_KEY")
if not secret_key:
    raise RuntimeError("SECRET_KEY is not set in your .env file. App cannot start.")
app.secret_key = secret_key

# --- Database Connections ---
def get_db_connection():
    conn = psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT")
    )
    return conn

# REPLACE lines 44-45 with:
try:
    mongo_client = MongoClient(os.getenv("MONGO_URI"), serverSelectionTimeoutMS=5000)
    mongo_client.server_info()
    mongo_db = mongo_client.get_database()
except Exception as e:
    print(f"WARNING: MongoDB connection failed: {e}")
    mongo_db = None


# ── Daily burn rate scheduler ──
def scheduled_burn_rate_job():
    """Runs every day at 8am — analyses all pharmacies."""
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute("SELECT id FROM pharmacies")
        pharmacy_ids = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        for pid in pharmacy_ids:
            run_analysis_and_alert(pid)
            print(f"Scheduled burn rate run complete for pharmacy {pid}")
    except Exception as e:
        print(f"Scheduled burn rate job error: {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(
    func=scheduled_burn_rate_job,
    trigger='cron',
    hour=8,
    minute=0,
    id='daily_burn_rate'
)
scheduler.start()
atexit.register(lambda: scheduler.shutdown())

# --- Routes ---
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email    = request.form.get('email', '')
        role = request.form.get('role', 'pharmacist')
        if role not in ('admin', 'pharmacist'):
            role = 'pharmacist'
        pharmacy_id = request.form['pharmacy_id']

        hashed_password = generate_password_hash(password)

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            # 2. NEW: Save the pharmacy_id into the users table
            cur.execute(
                "INSERT INTO users (username, password_hash, role, pharmacy_id, email) VALUES (%s, %s, %s, %s, %s)",
                (username, hashed_password, role, pharmacy_id, email)
            )
            conn.commit()
            cur.close()
            conn.close()
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except psycopg2.IntegrityError:
            flash('Username already exists!', 'danger')
            return redirect(url_for('register'))
        except Exception as e:
            print(f"Registration Error: {e}") 
            flash('An error occurred during registration.', 'danger')
            return redirect(url_for('register'))

    # 3. NEW FOR GET REQUEST: Fetch available pharmacies so the user can select one in the HTML dropdown
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM pharmacies ORDER BY name")
    pharmacies = cur.fetchall()
    cur.close()
    conn.close()
    
    return render_template('register.html', pharmacies=pharmacies)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        cur = conn.cursor()
        # 4. NEW: Select pharmacy_id from the database
        cur.execute("""
        SELECT u.user_id, u.username, u.password_hash, u.role, u.pharmacy_id, p.name
        FROM users u
        JOIN pharmacies p ON u.pharmacy_id = p.id
        WHERE u.username = %s
    """, (username,))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user and check_password_hash(user[2], password):
            session['user_id'] = user[0]
            session['username'] = user[1]
            session['role'] = user[3]
            # 5. NEW AND CRITICAL: Store the Tenant ID in the session
            session['pharmacy_id'] = user[4] 
            session['pharmacy_name'] = user[5]

            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'danger')

    return render_template('login.html')

#Dashboard Route 
@app.route('/dashboard')
@login_required
def dashboard():


    # 1. NEW: Grab the tenant ID from the session
    pharmacy_id = session.get('pharmacy_id') 

    conn = get_db_connection()
    cur = conn.cursor()
    
    # Query 1: Stat Cards (Filtered by pharmacy_id)
    cur.execute("SELECT COUNT(sale_id), SUM(total_amount) FROM sales WHERE DATE(sale_date) = CURRENT_DATE AND pharmacy_id = %s", (pharmacy_id,))
    sale_data = cur.fetchone()
    sales_today = sale_data[0] or 0
    revenue_today = sale_data[1] or 0.0

    cur.execute("SELECT COUNT(medicine_id) FROM medicines WHERE pharmacy_id = %s", (pharmacy_id,))
    total_medicines = cur.fetchone()[0] or 0
    
    cur.execute("SELECT COUNT(supplier_id) FROM suppliers WHERE pharmacy_id = %s", (pharmacy_id,))
    total_suppliers = cur.fetchone()[0] or 0

    # Query 2: Expiring List (Filtered by m.pharmacy_id)
    cur.execute("""
        SELECT m.name, b.batch_code, b.expiry_date, b.quantity
        FROM batches b JOIN medicines m ON b.medicine_id = m.medicine_id
        WHERE b.expiry_date BETWEEN CURRENT_DATE AND (CURRENT_DATE + INTERVAL '30 days')
        AND b.quantity > 0 AND m.pharmacy_id = %s ORDER BY b.expiry_date ASC LIMIT 5
    """, (pharmacy_id,))
    expiring_items = cur.fetchall()
    
    # Query 3: Recent Orders (Filtered by s.pharmacy_id)
    cur.execute("""
        SELECT s.sale_id, s.customer_name, s.total_amount, u.username, s.sale_date
        FROM sales s JOIN users u ON s.user_id = u.user_id
        WHERE s.pharmacy_id = %s
        ORDER BY s.sale_date DESC LIMIT 5
    """, (pharmacy_id,))
    recent_sales = cur.fetchall()

    # Query 4: Top Selling Medicines (Filtered by m.pharmacy_id)
    cur.execute("""
        SELECT m.name, SUM(si.total_price) as total_revenue
        FROM sale_items si
        JOIN batches b ON si.batch_id = b.batch_id
        JOIN medicines m ON b.medicine_id = m.medicine_id
        WHERE m.pharmacy_id = %s
        GROUP BY m.name
        ORDER BY total_revenue DESC
        LIMIT 5
    """, (pharmacy_id,))
    top_medicines = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('dashboard.html', sales_today=sales_today, revenue_today=revenue_today, total_medicines=total_medicines, total_suppliers=total_suppliers, expiring_items=expiring_items, recent_sales=recent_sales, top_medicines=top_medicines)


#Add Supplier Route 
@app.route('/add_supplier', methods=['GET', 'POST'])
@login_required
def add_supplier():
   

    pharmacy_id = session.get('pharmacy_id')

    if request.method == 'POST':
        name = request.form['name']
        contact = request.form['contact_person']
        phone = request.form['phone']
        email = request.form['email']
        address = request.form['address']

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            # 2. NEW: Insert the supplier attached to this specific pharmacy
            cur.execute(
                """INSERT INTO suppliers (name, contact_person, phone, email, address, pharmacy_id)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (name, contact, phone, email, address, pharmacy_id)
            )
            conn.commit()
            cur.close()
            conn.close()
            flash('Supplier added successfully!', 'success')
            return redirect(url_for('dashboard'))
        except Exception as e:
            print(f"Error: {e}")
            flash('Error adding supplier.', 'danger')

    return render_template('add_supplier.html')
   

#Add Medicine Route 
@app.route('/add_medicine', methods=['GET', 'POST'])
@login_required
def add_medicine():
   

    pharmacy_id = session.get('pharmacy_id')
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == 'POST':
        name = request.form['name']
        generic_name = request.form['generic_name']
        category = request.form['category']
        manufacturer = request.form['manufacturer']
        supplier_id = request.form['supplier_id']
        description = request.form['description']
        side_effects = request.form['side_effects']

        try:
            # 3. NEW: Isolate medicine in Postgres
            cur.execute(
                """INSERT INTO medicines (name, generic_name, category, manufacturer, supplier_id, pharmacy_id)
                   VALUES (%s, %s, %s, %s, %s, %s) RETURNING medicine_id""",
                (name, generic_name, category, manufacturer, supplier_id, pharmacy_id)
            )
            new_med_id = cur.fetchone()[0]
            conn.commit()

            # 4. NEW: Isolate medicine details in MongoDB
            mongo_db.medicine_details.insert_one({
                "medicine_id": new_med_id,
                "pharmacy_id": pharmacy_id, # Added to Mongo document
                "description": description,
                "side_effects": side_effects,
            })

            flash('Medicine added successfully!', 'success')
            return redirect(url_for('dashboard'))

        except Exception as e:
            conn.rollback()
            print(f"Error: {e}")
            flash(f'Error adding medicine: {e}', 'danger')

    # Only fetch suppliers belonging to THIS pharmacy
    cur.execute("SELECT supplier_id, name FROM suppliers WHERE pharmacy_id = %s ORDER BY name", (pharmacy_id,))
    suppliers = cur.fetchall()
    cur.close()
    conn.close()

    return render_template('add_medicine.html', suppliers=suppliers)


#medicines Route 
@app.route('/medicines')
@login_required
def view_medicines():
    
    pharmacy_id = session.get('pharmacy_id')
    conn = get_db_connection()
    cur = conn.cursor()
    # Filter list by pharmacy
    cur.execute("""
        SELECT m.medicine_id, m.name, m.category, m.manufacturer, COALESCE(s.name, 'No Supplier')
        FROM medicines m
        LEFT JOIN suppliers s ON m.supplier_id = s.supplier_id
        WHERE m.pharmacy_id = %s
        ORDER BY m.name
    """, (pharmacy_id,))
    medicines = cur.fetchall()
    cur.close()
    conn.close()

    return render_template('medicines.html', medicines=medicines)


@app.route('/medicine/<int:med_id>')
@login_required
def medicine_details(med_id):
    pharmacy_id = session.get('pharmacy_id')
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT m.*, s.name as supplier_name, s.phone as supplier_phone
        FROM medicines m
        LEFT JOIN suppliers s ON m.supplier_id = s.supplier_id
        WHERE m.medicine_id = %s AND m.pharmacy_id = %s
    """, (med_id, pharmacy_id))
    med_pg = cur.fetchone()

    cur.execute("""
        SELECT batch_code, expiry_date, quantity, buy_price, sell_price
        FROM batches WHERE medicine_id = %s ORDER BY expiry_date ASC
    """, (med_id,))
    batches = cur.fetchall()
    
    cur.close()
    conn.close()

    if not med_pg:
        flash('Medicine not found or access denied.', 'danger')
        return redirect(url_for('view_medicines'))

    # Fetch from Mongo ensuring tenant isolation
    med_mongo = mongo_db.medicine_details.find_one({"medicine_id": med_id, "pharmacy_id": pharmacy_id})

    return render_template('medicine_details.html', med=med_pg, details=med_mongo, batches=batches)

# Note: /add_batch remains mostly the same, but the medicine_id naturally isolates it.
# Note: /add_to_cart, /remove_from_cart, /sale_complete remain exactly the same as they just handle the session array.

@app.route('/new_sale')
@login_required
def new_sale():
    pharmacy_id = session.get('pharmacy_id')
    if 'cart' not in session:
        session['cart'] = []

    conn = get_db_connection()
    cur = conn.cursor()
    # Only show stock belonging to THIS pharmacy
    cur.execute("""
        SELECT b.batch_id, m.name, b.batch_code, b.expiry_date, b.quantity, b.sell_price
        FROM batches b
        JOIN medicines m ON b.medicine_id = m.medicine_id
        WHERE b.quantity > 0 AND b.expiry_date >= CURRENT_DATE AND m.pharmacy_id = %s
        ORDER BY m.name, b.expiry_date
    """, (pharmacy_id,))
    available_batches = cur.fetchall()
    cur.close()
    conn.close()

    cart_total = sum(item['quantity'] * item['sell_price'] for item in session['cart'])
    return render_template('new_sale.html', available_batches=available_batches, cart_items=session['cart'], cart_total=cart_total)


@app.route('/checkout', methods=['POST'])
@login_required
def checkout():
    if 'cart' not in session or not session['cart']:
        return redirect(url_for('new_sale'))
    pharmacy_id = session.get('pharmacy_id')
    cart = session['cart']
    customer_name = request.form.get('customer_name', 'Walk-in Customer')
    user_id = session['user_id']
    total_amount = sum(item['quantity'] * item['sell_price'] for item in cart)

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # 5. NEW: Attach the sale to the specific pharmacy
        cur.execute(
            """INSERT INTO sales (user_id, customer_name, total_amount, pharmacy_id)
               VALUES (%s, %s, %s, %s) RETURNING sale_id""",
            (user_id, customer_name, total_amount, pharmacy_id)
        )
        sale_id = cur.fetchone()[0]

        for item in cart:
            cur.execute(
                """INSERT INTO sale_items (sale_id, batch_id, quantity, price_per_unit)
                   VALUES (%s, %s, %s, %s)""",
                (sale_id, item['batch_id'], item['quantity'], item['sell_price'])
            )
        
        conn.commit()
        
        sale_details = {
            "sale_id": sale_id,
            "customer_name": customer_name,
            "total": total_amount,
            "items": cart
        }
        session['cart'] = []
        session['last_sale'] = sale_details
        
        return redirect(url_for('sale_complete'))

    except Exception as e:
        conn.rollback() 
        print(f"Checkout Error: {e}")
        flash('An error occurred during checkout.', 'danger')
        return redirect(url_for('new_sale'))
    finally:
        cur.close()
        conn.close()


@app.route('/api/monthly_sales')
@login_required
def api_monthly_sales():

    pharmacy_id = session.get('pharmacy_id')
    conn = get_db_connection()
    cur = conn.cursor()
    # Isolate chart data
    cur.execute("""
        SELECT 
            TO_CHAR(sale_date, 'Mon') as month_name,
            EXTRACT(MONTH FROM sale_date) as month_num,
            SUM(total_amount) as total
        FROM sales
        WHERE EXTRACT(YEAR FROM sale_date) = EXTRACT(YEAR FROM CURRENT_DATE) AND pharmacy_id = %s
        GROUP BY 1, 2
        ORDER BY month_num;
    """, (pharmacy_id,))
    sales_data = cur.fetchall()
    cur.close()
    conn.close()

    labels = [row[0] for row in sales_data]
    data = [float(row[2]) for row in sales_data]
    return jsonify(labels=labels, data=data)


@app.route('/api/daily_revenue_breakdown')
@login_required
def api_daily_revenue_breakdown():
    pharmacy_id = session.get('pharmacy_id')
    conn = get_db_connection()
    cur = conn.cursor()
    # Isolate chart data
    cur.execute("""
        SELECT SUM(total_amount) 
        FROM sales 
        WHERE DATE(sale_date) = CURRENT_DATE AND pharmacy_id = %s
    """, (pharmacy_id,))
    revenue_today = cur.fetchone()[0] or 0.0
    cur.close()
    conn.close()
    daily_goal = 5000.0
    remaining = max(0.0, daily_goal - float(revenue_today))
    data = [float(revenue_today), remaining]
    labels = ["Today's Earning", "Remaining Goal"]
    return jsonify(labels=labels, data=data)

# --- RESTORED MISSING ROUTES ---

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/add_batch', methods=['GET', 'POST'])
@login_required
def add_batch():
    pharmacy_id = session.get('pharmacy_id')

    if request.method == 'POST':
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            medicine_id = request.form.get('medicine_id')
            if not medicine_id:
                flash('You must select a medicine! If the list is empty, add a medicine first.', 'danger')
                # Redirect back with the med_id if we have it
                return redirect(url_for('add_batch'))

            # Verify this medicine belongs to the logged-in pharmacy
            cur.execute(
                "SELECT medicine_id FROM medicines WHERE medicine_id = %s AND pharmacy_id = %s",
                (medicine_id, pharmacy_id)
            )
            if not cur.fetchone():
                flash('Invalid medicine selection.', 'danger')
                return redirect(url_for('add_batch'))

            batch_code = request.form.get('batch_code')
            expiry_date = request.form.get('expiry_date')
            quantity = int(request.form.get('quantity'))
            buy_price = float(request.form.get('buy_price'))
            sell_price = float(request.form.get('sell_price'))

            cur.execute("""INSERT INTO batches (medicine_id, batch_code, expiry_date, quantity, buy_price, sell_price)
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (medicine_id, batch_code, expiry_date, quantity, buy_price, sell_price))
            conn.commit()
            flash('Stock/Batch added successfully!', 'success')
            # Redirect back to the medicine detail page if we know the med_id
            return redirect(url_for('medicine_details', med_id=medicine_id))

        except ValueError:
            flash('Please make sure quantity and prices are numbers!', 'warning')
        except Exception as e:
            conn.rollback()
            print(f"\n--- DB ERROR ---\n{e}\n----------------\n")
            flash('Database error! Check your terminal.', 'danger')
        finally:
            cur.close()
            conn.close()

    # GET request — pick up med_id from URL query param if coming from inventory
    med_id = request.args.get('med_id')

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT medicine_id, name FROM medicines WHERE pharmacy_id = %s ORDER BY name",
        (pharmacy_id,)
    )
    medicines = cur.fetchall()

    # If a specific medicine was pre-selected, fetch its name for display
    selected_medicine = None
    if med_id:
        cur.execute(
            "SELECT medicine_id, name FROM medicines WHERE medicine_id = %s AND pharmacy_id = %s",
            (med_id, pharmacy_id)
        )
        selected_medicine = cur.fetchone()

    cur.close()
    conn.close()

    return render_template('add_batch.html',
                           medicines=medicines,
                           med_id=med_id,
                           selected_medicine=selected_medicine)

@app.route('/add_to_cart', methods=['POST'])
@login_required
def add_to_cart():
    if 'cart' not in session:
        session['cart'] = []
    
    # batch_id = request.form.get('batch_id')
    # name = request.form.get('name')
    # quantity = int(request.form.get('quantity'))
    # sell_price = float(request.form.get('sell_price'))
    
    # cart = session['cart']
    # cart.append({'batch_id': batch_id, 'name': name, 'quantity': quantity, 'sell_price': sell_price})
    batch_id = request.form.get('batch_id')
    med_name = request.form.get('med_name')
    batch_code = request.form.get('batch_code')
    quantity = int(request.form.get('quantity'))
    sell_price = float(request.form.get('sell_price'))

    cart = session['cart']
    cart.append({
        'batch_id': batch_id,
        'med_name': med_name,
        'batch_code': batch_code,
        'quantity': quantity,
        'sell_price': sell_price
    })
    session['cart'] = cart
    
    flash(f'Added {quantity} of {med_name} to cart.', 'success')
    return redirect(url_for('new_sale'))

# @app.route('/remove_from_cart/<int:item_index>')
# def remove_from_cart(item_index):
#     if 'cart' in session:
#         cart = session['cart']
#         if 0 <= item_index < len(cart):
#             cart.pop(item_index)
#             session['cart'] = cart
#     return redirect(url_for('new_sale'))
@app.route('/remove_from_cart/<batch_id>')
@login_required
def remove_from_cart(batch_id):
    if 'cart' in session:
        cart = session['cart']
        cart = [item for item in cart if str(item['batch_id']) != str(batch_id)]
        session['cart'] = cart
    return redirect(url_for('new_sale'))

# @app.route('/sale_complete')
# def sale_complete():
#     if 'user_id' not in session: return redirect(url_for('login'))
#     last_sale = session.get('last_sale')
#     if not last_sale: return redirect(url_for('dashboard'))
#     return render_template('sale_complete.html', sale=last_sale)
@app.route('/sale_complete')
@login_required
def sale_complete():
    last_sale = session.get('last_sale')
    if not last_sale:
        return redirect(url_for('dashboard'))
    return render_template('sale_complete.html',
        sale_id=last_sale['sale_id'],
        customer_name=last_sale['customer_name'],
        total=last_sale['total'],
        items=last_sale['items']
    )
@app.route('/burn_rate', methods=['GET', 'POST'])
@login_required
def burn_rate_page():
    pharmacy_id = session.get('pharmacy_id')
    results     = []
    email_msg   = None
    last_run    = None

    if request.method == 'POST':
        # Manual trigger — run analysis AND send email
        results, email_msg = run_analysis_and_alert(pharmacy_id)
    else:
        # GET — just show last results from DB if they exist
        results = calculate_burn_rates(pharmacy_id)

    # Get last run time from DB
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute("""
            SELECT MAX(calculated_at) FROM burn_rate_log
            WHERE pharmacy_id = %s
        """, (pharmacy_id,))
        row = cur.fetchone()
        if row and row[0]:
            last_run = row[0].strftime('%d %b %Y, %H:%M')
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error fetching last run time: {e}")

    return render_template('burn_rate.html',
                           results=results,
                           email_msg=email_msg,
                           last_run=last_run)

@app.route('/reports')
@login_required
def reports_page():
    return render_template('reports.html')

@app.route('/generate_pdf', methods=['POST'])
@login_required
def generate_pdf_report():
    pharmacy_id = session.get('pharmacy_id')
    pharmacy_name = session.get('pharmacy_name')
    start_date = request.form['start_date']
    end_date = request.form['end_date']

    # 1. Gather the Tenant-Isolated Data
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT sale_date::date, customer_name, total_amount 
        FROM sales 
        WHERE pharmacy_id = %s AND sale_date >= %s AND sale_date <= %s
        ORDER BY sale_date ASC
    """, (pharmacy_id, start_date, f"{end_date} 23:59:59"))
    
    sales_data = cur.fetchall()
    cur.close()
    conn.close()

    if not sales_data:
        flash('No sales found for this date range.', 'warning')
        return redirect(url_for('reports_page'))

    # 2. Package the Data for Node.js
    payload = {
        "pharmacy_name": pharmacy_name,
        "report_type": "Sales History",
        "date_range": f"{start_date} to {end_date}",
        "data": [{"date": str(row[0]), "customer": row[1], "amount": float(row[2])} for row in sales_data]
    }

    # 3. Invoke the Node.js Microservice
    try:
        # NOTE: Make sure your EC2 instance has an IAM role allowing lambda:InvokeFunction
        client = boto3.client('lambda', region_name='ap-south-1') 
        response = client.invoke(
            FunctionName='StreamPulse-PDF-Generator', # The name of your Node Lambda
            InvocationType='RequestResponse',
            Payload=json.dumps(payload)
        )
        
        # 4. Read the returned S3 Presigned URL
        response_payload = json.loads(response['Payload'].read().decode('utf-8'))
        body = json.loads(response_payload['body'])
        
        # Redirect the user's browser directly to the secure S3 download link
        return redirect(body['download_url'])

    except Exception as e:
        print(f"Lambda Invocation Error: {e}")
        flash('Failed to generate PDF microservice. Check logs.', 'danger')
        return redirect(url_for('reports_page'))



if __name__ == '__main__':
    app.run(debug=True, port=5001)