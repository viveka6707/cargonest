# CargoNest – MySQL Edition with Cargo Load Distribution Optimizer

## Technology
- Flask + HTML/CSS/Bootstrap/JavaScript
- MySQL Connector/Python (MySQL `utf8` compatibility for older XAMPP/WAMP servers)
- Firebase Realtime Database for IoT sensor readings only
- Leaflet/OpenStreetMap for map display; no Google Maps API key
- Rule-based weighted container recommendation
- Cargo load distribution optimizer (largest-package-first balancing)

## Setup (Windows)
1. Start MySQL in XAMPP/WAMP.
2. Copy `.env.example` to `.env` and edit MySQL/Firebase settings.
3. Open terminal in this folder and run:
   ```bat
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   python app.py
   ```
4. Open http://127.0.0.1:5000

## Install CargoNest on a phone
CargoNest can be installed from its website as a Progressive Web App (PWA); no browser extension is needed. Deploy the site to a public HTTPS address first. Open that address in Chrome on Android and choose **Install app** (or **Add to Home screen**) when offered. On iPhone/iPad, open the site in Safari, tap **Share**, then **Add to Home Screen**. The app needs an internet connection to use the Flask service and database.

The configured MySQL database and tables are created on first run. The `load_optimizations` table is also created automatically; existing CargoNest databases do not need to be deleted.

Default initial admin credentials (change immediately after first login):
- Email: `admin@cargonest.local`
- Password: `Admin@123`

## Load Distribution Optimizer
Customer portal → **Load Optimizer**.
1. Select an approved container.
2. Enter individual package weights in kg, separated by commas or new lines (example: `120, 95, 80, 75, 60, 45, 30`).
3. The system sums all packages and rejects a plan if the total exceeds the container's declared maximum payload.
4. It sorts packages heaviest-first and assigns each package to the currently lightest of four simplified zones.
5. It shows zone weights, package assignments, payload utilization, remaining capacity and a load-imbalance indicator. The plan is saved in MySQL.

**Safety/engineering limitation:** this feature does not physically reduce cargo mass. It redistributes packages to improve balance in a simplified four-zone model. It is not a certified vehicle axle-load, center-of-gravity, floor point-load or lashing calculation. Operators must follow the container/vehicle manufacturer's payload and loading limits, applicable road regulations, and qualified loading guidance. Do not overload or use this tool as a substitute for weighing the loaded vehicle.

## Database split
- MySQL: users, containers, bookings, payments, ratings, recommendations, load optimization plans.
- Firebase: ESP32 sensor data (weight, ultrasonic/distance and GPS) only.

## Firebase
Set `FIREBASE_DB_URL`, optional `FIREBASE_AUTH_TOKEN`, and `FIREBASE_SENSOR_PATH` in `.env`. The default path matches the existing single-container firmware `/CargoNest/data`. For multiple containers, update firmware to write each container to its own node and set `FIREBASE_MULTI_CONTAINER=1`.

## Important
- Never expose Firebase admin credentials or production secrets in public source code.
- Change the default admin password and Flask secret before deployment.
- The map uses OpenStreetMap tiles and needs internet access; no paid map API key is used.
