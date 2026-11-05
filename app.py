import os, math, uuid, json
import mysql.connector
from mysql.connector import IntegrityError
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash


BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)
app.secret_key = os.environ.get('CARGONEST_SECRET', 'change-this-secret-before-deployment')

# ---------------- MySQL database ----------------
MYSQL_CONFIG = {
    'host': os.environ.get('MYSQL_HOST', '127.0.0.1'),
    'port': int(os.environ.get('MYSQL_PORT', '3306')),
    'user': os.environ.get('MYSQL_USER', 'root'),
    'password': os.environ.get('MYSQL_PASSWORD', ''),
    'database': os.environ.get('MYSQL_DATABASE', 'cargonest'),
    'charset': 'utf8',
    'collation': 'utf8_general_ci',
    'autocommit': False,
}

class HybridRow(dict):
    """Dictionary row that supports both row['column'] and row[0]."""
    def __getitem__(self, key):
        if isinstance(key, int):
            try:
                key = list(self.keys())[key]
            except IndexError:
                raise
        return super().__getitem__(key)

class CursorAdapter:
    def __init__(self, cursor):
        self.cursor = cursor
    def _row(self, row):
        return HybridRow(row) if row is not None else None
    def fetchone(self):
        return self._row(self.cursor.fetchone())
    def fetchall(self):
        return [self._row(row) for row in self.cursor.fetchall()]
    @property
    def lastrowid(self):
        return self.cursor.lastrowid
    @property
    def rowcount(self):
        return self.cursor.rowcount

class MySQLConnectionAdapter:
    def __init__(self, connection):
        self.connection = connection
    def execute(self, query, params=None):
        cursor = self.connection.cursor(dictionary=True)
        cursor.execute(query.replace('?', '%s'), params or ())
        return CursorAdapter(cursor)
    def executescript(self, script):
        # Schema statements contain no semicolons inside string literals.
        for statement in script.split(';'):
            statement = statement.strip()
            if statement:
                self.execute(statement)
    def commit(self):
        self.connection.commit()
    def close(self):
        self.connection.close()

def db():
    connection = mysql.connector.connect(**MYSQL_CONFIG)
    return MySQLConnectionAdapter(connection)

def init_db():
    # Create the configured database if it does not already exist.
    server_config = {k: v for k, v in MYSQL_CONFIG.items()
                     if k not in ('database', 'autocommit', 'charset', 'collation')}
    server = mysql.connector.connect(**server_config)
    cur = server.cursor()
    db_name = MYSQL_CONFIG['database'].replace('`', '')
    cur.execute(
        f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
        "CHARACTER SET utf8 COLLATE utf8_general_ci"
    )
    server.commit()
    cur.close()
    server.close()

    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users (
      id BIGINT PRIMARY KEY AUTO_INCREMENT,
      name VARCHAR(150) NOT NULL,
      email VARCHAR(191) NOT NULL UNIQUE,
      phone VARCHAR(40),
      password_hash VARCHAR(255) NOT NULL,
      role ENUM('admin','customer','provider') NOT NULL,
      status VARCHAR(30) NOT NULL DEFAULT 'active',
      created_at VARCHAR(40) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8;
    CREATE TABLE IF NOT EXISTS containers (
      id BIGINT PRIMARY KEY AUTO_INCREMENT,
      container_code VARCHAR(80) NOT NULL UNIQUE,
      provider_id BIGINT NOT NULL,
      container_type VARCHAR(100) NOT NULL,
      max_weight DOUBLE NOT NULL,
      total_space DOUBLE NOT NULL,
      price DOUBLE NOT NULL,
      pickup_city VARCHAR(150) NOT NULL,
      destination_city VARCHAR(150) NOT NULL,
      rating DOUBLE NOT NULL DEFAULT 4.0,
      status VARCHAR(30) NOT NULL DEFAULT 'pending',
      description TEXT,
      CONSTRAINT fk_containers_provider FOREIGN KEY(provider_id) REFERENCES users(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8;
    CREATE TABLE IF NOT EXISTS bookings (
      id BIGINT PRIMARY KEY AUTO_INCREMENT,
      booking_code VARCHAR(80) NOT NULL UNIQUE,
      customer_id BIGINT NOT NULL,
      provider_id BIGINT NOT NULL,
      container_id BIGINT NOT NULL,
      cargo_weight DOUBLE NOT NULL,
      required_space DOUBLE NOT NULL,
      pickup VARCHAR(150) NOT NULL,
      destination VARCHAR(150) NOT NULL,
      distance_km DOUBLE NOT NULL,
      eta_hours DOUBLE NOT NULL,
      amount DOUBLE NOT NULL,
      booking_status VARCHAR(30) NOT NULL DEFAULT 'requested',
      payment_status VARCHAR(30) NOT NULL DEFAULT 'unpaid',
      created_at VARCHAR(40) NOT NULL,
      CONSTRAINT fk_bookings_customer FOREIGN KEY(customer_id) REFERENCES users(id),
      CONSTRAINT fk_bookings_provider FOREIGN KEY(provider_id) REFERENCES users(id),
      CONSTRAINT fk_bookings_container FOREIGN KEY(container_id) REFERENCES containers(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8;
    CREATE TABLE IF NOT EXISTS payments (
      id BIGINT PRIMARY KEY AUTO_INCREMENT,
      booking_id BIGINT NOT NULL,
      transaction_code VARCHAR(80) NOT NULL UNIQUE,
      method VARCHAR(60) NOT NULL,
      amount DOUBLE NOT NULL,
      status VARCHAR(30) NOT NULL,
      created_at VARCHAR(40) NOT NULL,
      CONSTRAINT fk_payments_booking FOREIGN KEY(booking_id) REFERENCES bookings(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8;
    CREATE TABLE IF NOT EXISTS ratings (
      id BIGINT PRIMARY KEY AUTO_INCREMENT,
      booking_id BIGINT NOT NULL UNIQUE,
      customer_id BIGINT NOT NULL,
      provider_id BIGINT NOT NULL,
      stars INT NOT NULL,
      feedback TEXT,
      created_at VARCHAR(40) NOT NULL,
      CONSTRAINT fk_ratings_booking FOREIGN KEY(booking_id) REFERENCES bookings(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8;
    CREATE TABLE IF NOT EXISTS recommendations (
      id BIGINT PRIMARY KEY AUTO_INCREMENT,
      customer_id BIGINT NOT NULL,
      container_id BIGINT NOT NULL,
      score DOUBLE NOT NULL,
      eta_hours DOUBLE NOT NULL,
      estimated_cost DOUBLE NOT NULL,
      created_at VARCHAR(40) NOT NULL,
      CONSTRAINT fk_recommendations_customer FOREIGN KEY(customer_id) REFERENCES users(id),
      CONSTRAINT fk_recommendations_container FOREIGN KEY(container_id) REFERENCES containers(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8;
    CREATE TABLE IF NOT EXISTS load_optimizations (
      id BIGINT PRIMARY KEY AUTO_INCREMENT,
      customer_id BIGINT NOT NULL,
      container_id BIGINT NOT NULL,
      total_weight DOUBLE NOT NULL,
      capacity_weight DOUBLE NOT NULL,
      zone_weights TEXT NOT NULL,
      package_assignment TEXT NOT NULL,
      imbalance_percent DOUBLE NOT NULL,
      created_at VARCHAR(40) NOT NULL,
      CONSTRAINT fk_loadopt_customer FOREIGN KEY(customer_id) REFERENCES users(id),
      CONSTRAINT fk_loadopt_container FOREIGN KEY(container_id) REFERENCES containers(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8;
    """)
    admin = con.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()
    if not admin:
        con.execute(
            'INSERT INTO users(name,email,phone,password_hash,role,status,created_at) VALUES(?,?,?,?,?,?,?)',
            ( 'System Administrator',
              os.environ.get('ADMIN_EMAIL', 'admin@cargonest.local'), '',
              generate_password_hash(os.environ.get('ADMIN_PASSWORD', 'Admin@123')),
              'admin', 'active', datetime.now().isoformat(timespec='seconds'))
        )
    con.commit()
    con.close()

init_db()

# ---------------- Helpers ----------------
def current_user():
    if 'user_id' not in session: return None
    con=db(); row=con.execute('SELECT * FROM users WHERE id=?',(session['user_id'],)).fetchone(); con.close()
    return row

def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not current_user(): return redirect(url_for('login'))
        return fn(*a, **kw)
    return wrapper

def role_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            u=current_user()
            if not u: return redirect(url_for('login'))
            if u['role'] not in roles: abort(403)
            return fn(*a, **kw)
        return wrapper
    return deco

def haversine_km(lat1, lon1, lat2, lon2):
    r=6371.0
    p1,p2=math.radians(lat1),math.radians(lat2)
    dp=math.radians(lat2-lat1); dl=math.radians(lon2-lon1)
    a=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*r*math.asin(math.sqrt(a))

# City coordinates are used only for offline demo distance estimates.
CITY_COORDS={
 'chennai':(13.0827,80.2707),'bangalore':(12.9716,77.5946),'bengaluru':(12.9716,77.5946),
 'coimbatore':(11.0168,76.9558),'madurai':(9.9252,78.1198),'trichy':(10.7905,78.7047),
 'tiruchirappalli':(10.7905,78.7047),'salem':(11.6643,78.1460),'tirunelveli':(8.7139,77.7567),
 'hyderabad':(17.3850,78.4867),'mumbai':(19.0760,72.8777),'delhi':(28.6139,77.2090),
 'pune':(18.5204,73.8567),'kochi':(9.9312,76.2673),'kozhikode':(11.2588,75.7804)
}

def estimate_distance(pickup,destination):
    a=CITY_COORDS.get(pickup.strip().lower()); b=CITY_COORDS.get(destination.strip().lower())
    if not a or not b: return 100.0 # transparent demo fallback when city isn't in local list
    return haversine_km(a[0],a[1],b[0],b[1]) * 1.25 # approximate road-distance multiplier

def container_capacity_summary(con, container):
    """Return remaining booking capacity after reserving active bookings.

    Active bookings reserve both kg and CBM until delivered/rejected/cancelled.
    Sensor readings are physical measurements and are displayed separately;
    they are not added to reservations to avoid double counting the same cargo.
    """
    reserved = con.execute("""
        SELECT COALESCE(SUM(cargo_weight),0) AS reserved_weight,
               COALESCE(SUM(required_space),0) AS reserved_space
        FROM bookings
        WHERE container_id=?
          AND booking_status IN ('requested','accepted','picked_up','in_transit')
    """, (container['id'],)).fetchone()
    total_weight = float(container['max_weight'] or 0)
    total_space = float(container['total_space'] or 0)
    reserved_weight = float(reserved['reserved_weight'] or 0)
    reserved_space = float(reserved['reserved_space'] or 0)
    return {
        'total_weight': total_weight,
        'reserved_weight': reserved_weight,
        'available_weight': max(0.0, total_weight-reserved_weight),
        'total_space': total_space,
        'reserved_space': reserved_space,
        'available_space': max(0.0, total_space-reserved_space),
        'weight_utilization': round((reserved_weight/total_weight*100),1) if total_weight else 0,
        'space_utilization': round((reserved_space/total_space*100),1) if total_space else 0,
    }

def firebase_sensor(container_code):
    """Reads ESP32 Realtime Database node. Uses public RTDB REST read rules.
       Set FIREBASE_DB_URL and optionally FIREBASE_AUTH_TOKEN in environment.
    """
    import requests
    base=os.environ.get('FIREBASE_DB_URL','https://projectbase2027-acee2-default-rtdb.firebaseio.com').rstrip('/')
    # Current ESP32 sketch writes /CargoNest/data. Optional multi-container path can be configured.
    path=os.environ.get('FIREBASE_SENSOR_PATH','/CargoNest/data').strip('/')
    if os.environ.get('FIREBASE_MULTI_CONTAINER','0')=='1': path=f'CargoNest/containers/{container_code}/data'
    url=f'{base}/{path}.json'
    token=os.environ.get('FIREBASE_AUTH_TOKEN')
    params={'auth':token} if token else {}
    try:
        r=requests.get(url,params=params,timeout=4); r.raise_for_status(); return r.json() or {}
    except Exception as e:
        return {'_error':str(e)}

@app.context_processor
def inject_globals(): return {'logged_user':current_user(), 'now_year':datetime.now().year}

@app.route('/manifest.webmanifest')
def web_manifest():
    return send_from_directory(app.static_folder, 'manifest.webmanifest', mimetype='application/manifest+json')

@app.route('/service-worker.js')
def service_worker():
    response = send_from_directory(app.static_folder, 'service-worker.js', mimetype='application/javascript')
    response.headers['Cache-Control'] = 'no-cache'
    return response

@app.route('/')
def index():
    u=current_user()
    if not u: return redirect(url_for('login'))
    return redirect(url_for(u['role']+'_dashboard'))

# ---------------- Authentication ----------------
@app.route('/register',methods=['GET','POST'])
def register():
    if request.method=='POST':
        name=request.form.get('name','').strip(); email=request.form.get('email','').strip().lower()
        phone=request.form.get('phone','').strip(); password=request.form.get('password','')
        role=request.form.get('role','customer')
        if role not in ('customer','provider'): flash('Invalid registration role.','danger')
        elif not name or not email or len(password)<6: flash('Enter all required details. Password must be at least 6 characters.','danger')
        else:
            con=db()
            try:
                status='active' if role=='customer' else 'pending'
                con.execute('INSERT INTO users(name,email,phone,password_hash,role,status,created_at) VALUES(?,?,?,?,?,?,?)',
                  (name,email,phone,generate_password_hash(password),role,status,datetime.now().isoformat(timespec='seconds')))
                con.commit(); flash('Registration successful. Provider accounts require admin approval.' if role=='provider' else 'Registration successful. Please login.','success')
                return redirect(url_for('login'))
            except IntegrityError: flash('Email already registered.','danger')
            finally: con.close()
    return render_template('auth.html',mode='register')

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        email=request.form.get('email','').strip().lower(); password=request.form.get('password','')
        con=db(); u=con.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone(); con.close()
        if u and check_password_hash(u['password_hash'],password):
            if u['status']!='active': flash('Your account is pending admin approval or inactive.','warning')
            else:
                session.clear(); session['user_id']=u['id']; return redirect(url_for(u['role']+'_dashboard'))
        else: flash('Invalid email or password.','danger')
    return render_template('auth.html',mode='login')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

# ---------------- Admin ----------------
@app.route('/admin')
@role_required('admin')
def admin_dashboard():
    con=db(); stats={
      'customers':con.execute("SELECT COUNT(*) FROM users WHERE role='customer'").fetchone()[0],
      'providers':con.execute("SELECT COUNT(*) FROM users WHERE role='provider'").fetchone()[0],
      'containers':con.execute('SELECT COUNT(*) FROM containers').fetchone()[0],
      'bookings':con.execute('SELECT COUNT(*) FROM bookings').fetchone()[0],
      'revenue':con.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='success'").fetchone()[0]}
    recent=con.execute('''SELECT b.*,u.name customer,c.container_code FROM bookings b JOIN users u ON u.id=b.customer_id JOIN containers c ON c.id=b.container_id ORDER BY b.id DESC LIMIT 8''').fetchall()
    pending=con.execute("SELECT * FROM users WHERE role='provider' AND status='pending' ORDER BY id DESC").fetchall(); con.close()
    return render_template('admin.html',stats=stats,recent=recent,pending=pending,page='dashboard')

@app.route('/admin/users')
@role_required('admin')
def admin_users():
    con=db(); users=con.execute("SELECT * FROM users WHERE role!='admin' ORDER BY id DESC").fetchall(); con.close()
    return render_template('admin.html',users=users,page='users')

@app.route('/admin/user/<int:uid>/status/<status>',methods=['POST'])
@role_required('admin')
def admin_user_status(uid,status):
    if status not in ('active','inactive'): abort(400)
    con=db(); con.execute("UPDATE users SET status=? WHERE id=? AND role!='admin'",(status,uid)); con.commit(); con.close(); flash('User status updated.','success'); return redirect(request.referrer or url_for('admin_users'))

@app.route('/admin/containers')
@role_required('admin')
def admin_containers():
    con=db(); rows=con.execute('SELECT c.*,u.name provider FROM containers c JOIN users u ON u.id=c.provider_id ORDER BY c.id DESC').fetchall(); con.close()
    return render_template('admin.html',containers=rows,page='containers')

@app.route('/admin/container/<int:cid>/status/<status>',methods=['POST'])
@role_required('admin')
def admin_container_status(cid,status):
    if status not in ('approved','rejected','inactive'): abort(400)
    con=db(); con.execute('UPDATE containers SET status=? WHERE id=?',(status,cid)); con.commit(); con.close(); flash('Container status updated.','success'); return redirect(url_for('admin_containers'))

@app.route('/admin/bookings')
@role_required('admin')
def admin_bookings():
    con=db(); rows=con.execute('''SELECT b.*,cu.name customer,p.name provider,c.container_code FROM bookings b JOIN users cu ON cu.id=b.customer_id JOIN users p ON p.id=b.provider_id JOIN containers c ON c.id=b.container_id ORDER BY b.id DESC''').fetchall(); con.close()
    return render_template('admin.html',bookings=rows,page='bookings')

@app.route('/admin/payments')
@role_required('admin')
def admin_payments():
    con=db(); rows=con.execute('''SELECT p.*,b.booking_code,u.name customer FROM payments p JOIN bookings b ON b.id=p.booking_id JOIN users u ON u.id=b.customer_id ORDER BY p.id DESC''').fetchall(); con.close()
    return render_template('admin.html',payments=rows,page='payments')

@app.route('/admin/tracking')
@role_required('admin')
def admin_tracking():
    con=db(); rows=con.execute('''SELECT c.id,c.container_code,b.booking_code,b.pickup,b.destination,b.booking_status FROM containers c LEFT JOIN bookings b ON b.container_id=c.id AND b.id=(SELECT MAX(id) FROM bookings WHERE container_id=c.id) WHERE c.status='approved' ''').fetchall(); con.close()
    return render_template('admin.html',tracking=rows,page='tracking')

# ---------------- Provider ----------------
@app.route('/provider')
@role_required('provider')
def provider_dashboard():
    u=current_user(); con=db(); stats={'containers':con.execute('SELECT COUNT(*) FROM containers WHERE provider_id=?',(u['id'],)).fetchone()[0],
      'bookings':con.execute('SELECT COUNT(*) FROM bookings WHERE provider_id=?',(u['id'],)).fetchone()[0],
      'pending':con.execute("SELECT COUNT(*) FROM bookings WHERE provider_id=? AND booking_status='requested'",(u['id'],)).fetchone()[0],
      'earnings':con.execute("SELECT COALESCE(SUM(p.amount),0) FROM payments p JOIN bookings b ON b.id=p.booking_id WHERE b.provider_id=? AND p.status='success'",(u['id'],)).fetchone()[0]}
    rows=con.execute('SELECT * FROM containers WHERE provider_id=? ORDER BY id DESC',(u['id'],)).fetchall(); con.close()
    return render_template('provider.html',page='dashboard',stats=stats,containers=rows)

@app.route('/provider/containers',methods=['GET','POST'])
@role_required('provider')
def provider_containers():
    u=current_user(); con=db()
    if request.method=='POST':
        try:
            code=request.form['container_code'].strip().upper(); typ=request.form['container_type']; mw=float(request.form['max_weight']); space=float(request.form['total_space']); price=float(request.form['price']); pickup=request.form['pickup_city'].strip(); dest=request.form['destination_city'].strip()
            if min(mw,space,price)<=0 or not code or not pickup or not dest: raise ValueError()
            con.execute('INSERT INTO containers(container_code,provider_id,container_type,max_weight,total_space,price,pickup_city,destination_city,status,description) VALUES(?,?,?,?,?,?,?,?,?,?)',(code,u['id'],typ,mw,space,price,pickup,dest,'pending',request.form.get('description','')))
            con.commit(); flash('Container added. Admin approval is required before it appears in customer search.','success')
        except (ValueError,KeyError,IntegrityError): flash('Invalid details or container ID already exists.','danger')
        finally: con.close()
        return redirect(url_for('provider_containers'))
    rows=con.execute('SELECT * FROM containers WHERE provider_id=? ORDER BY id DESC',(u['id'],)).fetchall(); con.close()
    return render_template('provider.html',page='containers',containers=rows)

@app.route('/provider/bookings')
@role_required('provider')
def provider_bookings():
    u=current_user(); con=db(); rows=con.execute('''SELECT b.*,cu.name customer,cu.phone,c.container_code FROM bookings b JOIN users cu ON cu.id=b.customer_id JOIN containers c ON c.id=b.container_id WHERE b.provider_id=? ORDER BY b.id DESC''',(u['id'],)).fetchall(); con.close()
    return render_template('provider.html',page='bookings',bookings=rows)

@app.route('/provider/booking/<int:bid>/<action>',methods=['POST'])
@role_required('provider')
def provider_booking_action(bid,action):
    if action not in ('accept','reject','picked','transit','delivered'): abort(400)
    status={'accept':'accepted','reject':'rejected','picked':'picked_up','transit':'in_transit','delivered':'delivered'}[action]
    u=current_user(); con=db(); b=con.execute('SELECT * FROM bookings WHERE id=? AND provider_id=?',(bid,u['id'])).fetchone()
    if not b: con.close(); abort(404)
    con.execute('UPDATE bookings SET booking_status=? WHERE id=?',(status,bid)); con.commit(); con.close(); flash('Booking status updated.','success'); return redirect(url_for('provider_bookings'))

# ---------------- Customer ----------------
@app.route('/customer')
@role_required('customer')
def customer_dashboard():
    u=current_user(); con=db(); rows=con.execute('''SELECT b.*,c.container_code FROM bookings b JOIN containers c ON c.id=b.container_id WHERE b.customer_id=? ORDER BY b.id DESC LIMIT 5''',(u['id'],)).fetchall(); count=con.execute('SELECT COUNT(*) FROM bookings WHERE customer_id=?',(u['id'],)).fetchone()[0]; con.close()
    return render_template('customer.html',page='dashboard',bookings=rows,count=count)

@app.route('/customer/search',methods=['GET','POST'])
@role_required('customer')
def customer_search():
    results=[]
    if request.method=='POST':
        con=None
        try:
            weight=float(request.form['weight']); space=float(request.form['space'])
            pickup=request.form['pickup'].strip(); dest=request.form['destination'].strip()
            if weight<=0 or space<=0 or not pickup or not dest: raise ValueError()
            distance=estimate_distance(pickup,dest); speed=45.0; eta=distance/speed
            con=db()
            containers=con.execute("SELECT c.*,u.name provider FROM containers c JOIN users u ON u.id=c.provider_id WHERE c.status='approved' AND u.status='active'").fetchall()
            eligible=[]
            for c in containers:
                cap=container_capacity_summary(con,c)
                # Only show containers with enough unreserved weight AND CBM.
                if cap['available_weight'] >= weight and cap['available_space'] >= space:
                    eligible.append((c,cap))
            min_price=min([float(c['price']) for c,_ in eligible] or [1.0])
            for c,cap in eligible:
                capacity_score=min(100,(cap['available_weight']/weight)*50) if weight else 0
                space_score=min(100,(cap['available_space']/space)*50) if space else 0
                cost_score=max(0,100-(float(c['price'])/max(1,min_price)-1)*35)
                rating_score=(float(c['rating'])/5)*100
                eta_score=max(0,100-(eta/24)*30)
                score=0.30*capacity_score+0.20*space_score+0.15*cost_score+0.15*rating_score+0.20*eta_score
                results.append({'container':c,'score':round(score,1),'distance':round(distance,1),'eta':round(eta,1),'amount':round(float(c['price']),2),'pickup':pickup,'destination':dest,'weight':weight,'space':space,**cap})
            results.sort(key=lambda x:x['score'],reverse=True)
            con.execute('DELETE FROM recommendations WHERE customer_id=?',(current_user()['id'],))
            for x in results:
                con.execute('INSERT INTO recommendations(customer_id,container_id,score,eta_hours,estimated_cost,created_at) VALUES(?,?,?,?,?,?)',(current_user()['id'],x['container']['id'],x['score'],x['eta'],x['amount'],datetime.now().isoformat(timespec='seconds')))
            con.commit()
            session['last_search']={'weight':weight,'space':space,'pickup':pickup,'destination':dest,'distance':distance}
            if not results:
                flash('No container has enough remaining unreserved weight and CBM. Check current bookings or choose another container.','warning')
        except (ValueError,KeyError):
            flash('Enter valid weight, space, pickup and destination.','danger')
        finally:
            if con: con.close()
    return render_template('customer.html',page='search',results=results,last_search=session.get('last_search'))

@app.route('/customer/book/<int:cid>',methods=['POST'])
@role_required('customer')
def customer_book(cid):
    u=current_user(); s=session.get('last_search')
    if not s:
        flash('Search for a container before booking.','warning')
        return redirect(url_for('customer_search'))
    con=db()
    c=con.execute("SELECT * FROM containers WHERE id=? AND status='approved'",(cid,)).fetchone()
    if not c:
        con.close(); flash('Container not found or not approved.','danger')
        return redirect(url_for('customer_search'))
    cap=container_capacity_summary(con,c)
    if cap['available_weight'] < float(s['weight']) or cap['available_space'] < float(s['space']):
        con.close(); flash('This container no longer has enough remaining capacity. Please search again.','warning')
        return redirect(url_for('customer_search'))
    code='CN-'+uuid.uuid4().hex[:8].upper(); eta=s['distance']/45.0
    con.execute('INSERT INTO bookings(booking_code,customer_id,provider_id,container_id,cargo_weight,required_space,pickup,destination,distance_km,eta_hours,amount,booking_status,payment_status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
      (code,u['id'],c['provider_id'],cid,s['weight'],s['space'],s['pickup'],s['destination'],s['distance'],eta,c['price'],'requested','unpaid',datetime.now().isoformat(timespec='seconds')))
    con.commit()
    bid=con.execute('SELECT id FROM bookings WHERE booking_code=?',(code,)).fetchone()['id']
    con.close(); flash('Booking request created. The selected weight and CBM are now reserved while the booking is active.','success')
    return redirect(url_for('customer_payment',bid=bid))

@app.route('/customer/payment/<int:bid>',methods=['GET','POST'])
@role_required('customer')
def customer_payment(bid):
    u=current_user(); con=db(); b=con.execute('SELECT b.*,c.container_code FROM bookings b JOIN containers c ON c.id=b.container_id WHERE b.id=? AND b.customer_id=?',(bid,u['id'])).fetchone()
    if not b: con.close(); abort(404)
    if request.method=='POST':
        if b['booking_status'] != 'accepted':
            flash('Provider must accept this booking before demo payment can be completed.','warning')
        else:
            status=request.form.get('result','success'); method=request.form.get('method','UPI Demo')
            if status not in ('success','failed','pending'): status='failed'
            tx='DEMO-'+uuid.uuid4().hex[:10].upper()
            con.execute('INSERT INTO payments(booking_id,transaction_code,method,amount,status,created_at) VALUES(?,?,?,?,?,?)',(bid,tx,method,b['amount'],status,datetime.now().isoformat(timespec='seconds')))
            con.execute('UPDATE bookings SET payment_status=? WHERE id=?',(status,bid))
            if status=='success' and b['booking_status']=='requested':
                # Payment is simulated; booking still awaits provider acceptance.
                pass
            con.commit(); flash(f'Demo payment {status.upper()}. Transaction: {tx}','success' if status=='success' else 'warning')
            b=con.execute('SELECT b.*,c.container_code FROM bookings b JOIN containers c ON c.id=b.container_id WHERE b.id=?',(bid,)).fetchone()
    payments=con.execute('SELECT * FROM payments WHERE booking_id=? ORDER BY id DESC',(bid,)).fetchall(); con.close()
    return render_template('customer.html',page='payment',booking=b,payments=payments)

@app.route('/customer/bookings')
@role_required('customer')
def customer_bookings():
    u=current_user(); con=db(); rows=con.execute('''SELECT b.*,c.container_code,p.name provider FROM bookings b JOIN containers c ON c.id=b.container_id JOIN users p ON p.id=b.provider_id WHERE b.customer_id=? ORDER BY b.id DESC''',(u['id'],)).fetchall(); con.close()
    return render_template('customer.html',page='bookings',bookings=rows)

@app.route('/customer/tracking/<int:bid>')
@role_required('customer')
def customer_tracking(bid):
    con=db(); b=con.execute('SELECT b.*,c.container_code FROM bookings b JOIN containers c ON c.id=b.container_id WHERE b.id=? AND b.customer_id=?',(bid,current_user()['id'],)).fetchone(); con.close()
    if not b: abort(404)
    return render_template('tracking.html',booking=b,admin=False)

@app.route('/customer/rate/<int:bid>',methods=['POST'])
@role_required('customer')
def customer_rate(bid):
    stars=int(request.form.get('stars',5)); feedback=request.form.get('feedback','').strip(); u=current_user(); con=db(); b=con.execute("SELECT * FROM bookings WHERE id=? AND customer_id=? AND booking_status='delivered'",(bid,u['id'])).fetchone()
    if not b: con.close(); flash('Only delivered bookings can be rated.','warning'); return redirect(url_for('customer_bookings'))
    try:
        con.execute('INSERT INTO ratings(booking_id,customer_id,provider_id,stars,feedback,created_at) VALUES(?,?,?,?,?,?)',(bid,u['id'],b['provider_id'],stars,feedback,datetime.now().isoformat(timespec='seconds')))
        con.execute('UPDATE containers SET rating=(SELECT AVG(stars) FROM ratings WHERE provider_id=?) WHERE provider_id=?',(b['provider_id'],b['provider_id']))
        con.commit(); flash('Thank you for your feedback.','success')
    except IntegrityError: flash('You have already rated this booking.','warning')
    finally: con.close()
    return redirect(url_for('customer_bookings'))


# ---------------- Cargo load distribution optimizer ----------------
def balance_load_packages(package_weights, zone_count=4):
    """Greedy largest-first load balancing. Redistributes packages; it never reduces mass."""
    zones = [{'weight': 0.0, 'packages': []} for _ in range(zone_count)]
    indexed = sorted(enumerate(package_weights, start=1), key=lambda item: item[1], reverse=True)
    for package_no, weight in indexed:
        target = min(range(zone_count), key=lambda idx: zones[idx]['weight'])
        zones[target]['weight'] += weight
        zones[target]['packages'].append({'package': package_no, 'weight': round(weight, 2)})
    weights = [round(zone['weight'], 2) for zone in zones]
    total = sum(weights)
    average = total / zone_count if zone_count else 0
    imbalance = ((max(weights) - min(weights)) / average * 100) if average else 0
    return weights, zones, round(imbalance, 2)

@app.route('/customer/load-optimization', methods=['GET', 'POST'])
@role_required('customer')
def customer_load_optimization():
    u = current_user()
    con = db()
    containers = con.execute("SELECT id, container_code, container_type, max_weight FROM containers WHERE status='approved' ORDER BY container_code").fetchall()
    result = None
    selected_id = request.form.get('container_id', '')
    raw_weights = request.form.get('package_weights', '')
    if request.method == 'POST':
        try:
            if not selected_id:
                raise ValueError('Select an approved container.')
            package_weights = [float(x.strip()) for x in raw_weights.replace(';', ',').replace('\n', ',').split(',') if x.strip()]
            if not package_weights or len(package_weights) > 200 or any((not math.isfinite(x) or x <= 0) for x in package_weights):
                raise ValueError('Enter 1 to 200 positive package weights in kg.')
            container = con.execute("SELECT * FROM containers WHERE id=? AND status='approved'", (int(selected_id),)).fetchone()
            if not container:
                raise ValueError('Selected container is not available.')
            total_weight = round(sum(package_weights), 2)
            if total_weight > float(container['max_weight']):
                raise ValueError(f'Total load {total_weight:.2f} kg exceeds container capacity {container["max_weight"]:.2f} kg. Remove cargo or select a higher-capacity container; do not overload.')
            zone_weights, zones, imbalance = balance_load_packages(package_weights, 4)
            con.execute('INSERT INTO load_optimizations(customer_id,container_id,total_weight,capacity_weight,zone_weights,package_assignment,imbalance_percent,created_at) VALUES(?,?,?,?,?,?,?,?)',
                (u['id'], container['id'], total_weight, container['max_weight'], json.dumps(zone_weights), json.dumps(zones), imbalance, datetime.now().isoformat(timespec='seconds')))
            con.commit()
            result = {'container': container, 'total_weight': total_weight, 'capacity': container['max_weight'],
                      'remaining_capacity': round(float(container['max_weight'])-total_weight, 2),
                      'utilization': round(total_weight/float(container['max_weight'])*100, 1),
                      'zone_weights': zone_weights, 'zones': zones, 'imbalance': imbalance,
                      'package_count': len(package_weights)}
            flash('Balanced loading plan generated and saved.', 'success')
        except (ValueError, TypeError, OverflowError) as exc:
            flash(str(exc), 'danger')
    history = con.execute("SELECT l.*, c.container_code FROM load_optimizations l JOIN containers c ON c.id=l.container_id WHERE l.customer_id=? ORDER BY l.id DESC LIMIT 10", (u['id'],)).fetchall()
    con.close()
    return render_template('load_optimization.html', containers=containers, result=result,
                           selected_id=selected_id, raw_weights=raw_weights, history=history)

# ---------------- JSON APIs: Firebase IoT + map ----------------
@app.route('/api/sensor/<container_code>')
@login_required
def api_sensor(container_code):
    u=current_user(); con=db(); c=con.execute('SELECT * FROM containers WHERE container_code=?',(container_code,)).fetchone(); con.close()
    if not c: return jsonify({'error':'Container not found'}),404
    if u['role']=='provider' and c['provider_id']!=u['id']: abort(403)
    if u['role']=='customer':
        con=db(); allowed=con.execute('SELECT 1 FROM bookings WHERE container_id=? AND customer_id=?',(c['id'],u['id'])).fetchone(); con.close()
        if not allowed: abort(403)
    data=firebase_sensor(container_code)
    return jsonify(data)

@app.route('/api/admin/sensors')
@role_required('admin')
def api_admin_sensors():
    con=db(); cs=con.execute("SELECT container_code FROM containers WHERE status='approved'").fetchall(); con.close()
    return jsonify({c['container_code']:firebase_sensor(c['container_code']) for c in cs})

@app.route('/api/container/<int:cid>/location')
@login_required
def api_container_location(cid):
    u=current_user(); con=db(); c=con.execute('SELECT * FROM containers WHERE id=?',(cid,)).fetchone(); con.close()
    if not c: abort(404)
    if u['role']=='provider' and c['provider_id']!=u['id']: abort(403)
    if u['role']=='customer':
        con=db(); ok=con.execute('SELECT 1 FROM bookings WHERE container_id=? AND customer_id=?',(cid,u['id'])).fetchone(); con.close()
        if not ok: abort(403)
    return jsonify(firebase_sensor(c['container_code']))

@app.errorhandler(403)
def forbidden(e): return render_template('error.html',code=403,message='You do not have permission to access this page.'),403
@app.errorhandler(404)
def not_found(e): return render_template('error.html',code=404,message='The requested page was not found.'),404

if __name__=='__main__':
    app.run(host='127.0.0.1',port=int(os.environ.get('PORT',5000)),debug=os.environ.get('FLASK_DEBUG','0')=='1')
