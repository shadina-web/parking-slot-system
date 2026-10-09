from flask import Flask, render_template, request, redirect, url_for, session, flash
import mysql.connector
from datetime import date, datetime
from werkzeug.security import generate_password_hash, check_password_hash
from config import DB_CONFIG

app = Flask(__name__)

# Secret key for sessions
app.secret_key = "college_parking_secret_key"


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():
    return redirect(url_for("login"))


# =========================================================
# REGISTER
# =========================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form["name"]
        email = request.form["email"]
        phone = request.form["phone"]
        password = request.form["password"]
        role = request.form["role"]

        hashed_password = generate_password_hash(password)

        try:

            connection = get_db_connection()
            cursor = connection.cursor()

            query = """
                INSERT INTO users
                (name, email, password, role, phone)
                VALUES (%s, %s, %s, %s, %s)
            """

            values = (
                name,
                email,
                hashed_password,
                role,
                phone
            )

            cursor.execute(query, values)

            connection.commit()

            cursor.close()
            connection.close()

            flash(
                "Registration successful! Please login.",
                "success"
            )

            return redirect(url_for("login"))

        except mysql.connector.IntegrityError:

            flash(
                "Email already registered.",
                "error"
            )

        except mysql.connector.Error as error:

            flash(
                f"Database error: {error}",
                "error"
            )

    return render_template("register.html")


# =========================================================
# LOGIN
# =========================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form["email"]
        password = request.form["password"]

        try:

            connection = get_db_connection()

            cursor = connection.cursor(
                dictionary=True
            )

            query = """
                SELECT *
                FROM users
                WHERE email = %s
            """

            cursor.execute(
                query,
                (email,)
            )

            user = cursor.fetchone()

            cursor.close()
            connection.close()

            if user and check_password_hash(
                user["password"],
                password
            ):

                session["user_id"] = user["id"]
                session["name"] = user["name"]
                session["role"] = user["role"]

                return redirect(
                    url_for("dashboard")
                )

            else:

                flash(
                    "Invalid email or password.",
                    "error"
                )

        except mysql.connector.Error as error:

            flash(
                f"Database error: {error}",
                "error"
            )

    return render_template("login.html")


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:
        return redirect(url_for("login"))

    return render_template(
        "dashboard.html",
        name=session["name"],
        role=session["role"]
    )


# =========================================================
# PARKING SLOTS
# =========================================================

@app.route("/parking-slots")
def parking_slots():

    if "user_id" not in session:
        return redirect(url_for("login"))

    try:

        connection = get_db_connection()

        cursor = connection.cursor(
            dictionary=True
        )

        query = """
            SELECT
                id,
                slot_number,
                vehicle_type,
                status,
                location
            FROM parking_slots
            ORDER BY slot_number
        """

        cursor.execute(query)

        slots = cursor.fetchall()

        cursor.close()
        connection.close()

        return render_template(
            "parking_slots.html",
            slots=slots,
            name=session["name"]
        )

    except mysql.connector.Error as error:

        return f"""
            <h1>Database Error</h1>
            <p>{error}</p>
        """


# =========================================================
# BOOK SLOT
# =========================================================

@app.route("/book-slot/<int:slot_id>")
def book_slot(slot_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT id, slot_number, vehicle_type, status, location
            FROM parking_slots
            WHERE id = %s
        """, (slot_id,))

        slot = cursor.fetchone()

        if not slot:
            flash("Parking slot not found.", "error")
            return redirect(url_for("parking_slots"))

        if slot["status"] != "Available":
            flash("This parking slot is no longer available.", "error")
            return redirect(url_for("parking_slots"))

        cursor.execute("""
            SELECT id, vehicle_number, vehicle_type, vehicle_model
            FROM vehicles
            WHERE user_id = %s AND vehicle_type = %s
            ORDER BY created_at DESC, id DESC
        """, (session["user_id"], slot["vehicle_type"]))

        vehicles = cursor.fetchall()

        return render_template(
            "book_slot.html",
            slot=slot,
            vehicles=vehicles,
            name=session["name"],
            today=date.today().isoformat()
        )

    except mysql.connector.Error as error:

        flash(f"Database error: {error}", "error")
        return redirect(url_for("parking_slots"))

    finally:

        if cursor:
            cursor.close()
        if connection:
            connection.close()


@app.route("/confirm-booking/<int:slot_id>", methods=["POST"])
def confirm_booking(slot_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    vehicle_id = request.form.get("vehicle_id", "").strip()
    booking_date = request.form.get("booking_date", "").strip()
    start_time = request.form.get("start_time", "").strip()
    end_time = request.form.get("end_time", "").strip()

    if not all([vehicle_id, booking_date, start_time, end_time]):
        flash("Please complete all booking fields.", "error")
        return redirect(url_for("book_slot", slot_id=slot_id))

    try:
        vehicle_id = int(vehicle_id)
        selected_date = datetime.strptime(booking_date, "%Y-%m-%d").date()
        selected_start = datetime.strptime(start_time, "%H:%M").time()
        selected_end = datetime.strptime(end_time, "%H:%M").time()
    except (TypeError, ValueError):
        flash("Please enter valid booking details.", "error")
        return redirect(url_for("book_slot", slot_id=slot_id))

    if selected_date < date.today():
        flash("Booking date cannot be in the past.", "error")
        return redirect(url_for("book_slot", slot_id=slot_id))

    if selected_start >= selected_end:
        flash("End time must be later than start time.", "error")
        return redirect(url_for("book_slot", slot_id=slot_id))

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT id, vehicle_type, status
            FROM parking_slots
            WHERE id = %s
            FOR UPDATE
        """, (slot_id,))

        slot = cursor.fetchone()

        if not slot:
            connection.rollback()
            flash("Parking slot not found.", "error")
            return redirect(url_for("parking_slots"))

        if slot["status"] != "Available":
            connection.rollback()
            flash("This parking slot is no longer available.", "error")
            return redirect(url_for("parking_slots"))

        cursor.execute("""
            SELECT id, vehicle_type
            FROM vehicles
            WHERE id = %s AND user_id = %s
        """, (vehicle_id, session["user_id"]))

        vehicle = cursor.fetchone()

        if not vehicle:
            connection.rollback()
            flash("Please select one of your registered vehicles.", "error")
            return redirect(url_for("book_slot", slot_id=slot_id))

        if vehicle["vehicle_type"] != slot["vehicle_type"]:
            connection.rollback()
            flash("The selected vehicle type does not match this slot.", "error")
            return redirect(url_for("book_slot", slot_id=slot_id))

        cursor.execute("""
            INSERT INTO bookings
                (user_id, vehicle_id, slot_id, booking_date, start_time, end_time, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            session["user_id"], vehicle_id, slot_id, booking_date,
            start_time, end_time, "Active"
        ))

        cursor.execute("""
            UPDATE parking_slots
            SET status = 'Reserved'
            WHERE id = %s AND status = 'Available'
        """, (slot_id,))

        if cursor.rowcount != 1:
            connection.rollback()
            flash("This parking slot is no longer available.", "error")
            return redirect(url_for("parking_slots"))

        connection.commit()
        flash("Parking slot booked successfully.", "success")
        return redirect(url_for("my_bookings"))

    except mysql.connector.Error as error:

        if connection:
            connection.rollback()
        flash(f"Could not complete booking: {error}", "error")
        return redirect(url_for("book_slot", slot_id=slot_id))

    finally:

        if cursor:
            cursor.close()
        if connection:
            connection.close()


@app.route("/cancel-booking/<int:booking_id>", methods=["POST"])
def cancel_booking(booking_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT b.id, b.slot_id, b.status
            FROM bookings b
            WHERE b.id = %s AND b.user_id = %s
            FOR UPDATE
        """, (booking_id, session["user_id"]))

        booking = cursor.fetchone()

        if not booking:
            connection.rollback()
            flash("Booking not found.", "error")
            return redirect(url_for("my_bookings"))

        if booking["status"] != "Active":
            connection.rollback()
            flash("Only active bookings can be cancelled.", "error")
            return redirect(url_for("my_bookings"))

        cursor.execute("""
            UPDATE bookings
            SET status = 'Cancelled'
            WHERE id = %s AND user_id = %s AND status = 'Active'
        """, (booking_id, session["user_id"]))

        cursor.execute("""
            UPDATE parking_slots
            SET status = 'Available'
            WHERE id = %s AND status = 'Reserved'
        """, (booking["slot_id"],))

        if cursor.rowcount != 1:
            connection.rollback()
            flash("The parking slot could not be released.", "error")
            return redirect(url_for("my_bookings"))

        connection.commit()
        flash("Booking cancelled successfully.", "success")
        return redirect(url_for("my_bookings"))

    except mysql.connector.Error as error:

        if connection:
            connection.rollback()
        flash(f"Could not cancel booking: {error}", "error")
        return redirect(url_for("my_bookings"))

    finally:

        if cursor:
            cursor.close()
        if connection:
            connection.close()


# =========================================================
# MY VEHICLES
# =========================================================

@app.route("/my-vehicles")
def my_vehicles():

    if "user_id" not in session:
        return redirect(url_for("login"))

    try:

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        query = """
            SELECT
                vehicle_number,
                vehicle_type,
                vehicle_model
            FROM vehicles
            WHERE user_id = %s
            ORDER BY created_at DESC, id DESC
        """

        cursor.execute(query, (session["user_id"],))
        vehicles = cursor.fetchall()

        cursor.close()
        connection.close()

        return render_template(
            "my_vehicles.html",
            vehicles=vehicles,
            name=session["name"]
        )

    except mysql.connector.Error as error:

        return f"""
            <h1>Database Error</h1>
            <p>{error}</p>
        """


# =========================================================
# DEVELOPMENT MOCK VEHICLES
# Remove this route after development testing is complete.
# =========================================================

@app.route("/add-mock-vehicles")
def add_mock_vehicles():

    if "user_id" not in session:
        return redirect(url_for("login"))

    mock_vehicles = [
        ("KL08AB1234", "Two Wheeler", "Honda Activa"),
        ("KL08CD5678", "Two Wheeler", "TVS Jupiter"),
        ("KL08EF9012", "Four Wheeler", "Hyundai i20"),
        ("KL08GH3456", "Four Wheeler", "Maruti Swift"),
        ("KL08IJ7890", "Two Wheeler", "Yamaha FZ")
    ]

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor()

        query = """
            INSERT IGNORE INTO vehicles
                (user_id, vehicle_number, vehicle_type, vehicle_model)
            VALUES (%s, %s, %s, %s)
        """

        values = [
            (session["user_id"], vehicle_number, vehicle_type, vehicle_model)
            for vehicle_number, vehicle_type, vehicle_model in mock_vehicles
        ]

        cursor.executemany(query, values)
        connection.commit()

        flash("Mock vehicles are ready for testing.", "success")
        return redirect(url_for("my_vehicles"))

    except mysql.connector.Error as error:

        if connection:
            connection.rollback()
        flash(f"Could not add mock vehicles: {error}", "error")
        return redirect(url_for("my_vehicles"))

    finally:

        if cursor:
            cursor.close()
        if connection:
            connection.close()


# =========================================================
# MY BOOKINGS
# =========================================================

@app.route("/my-bookings")
def my_bookings():

    if "user_id" not in session:
        return redirect(url_for("login"))

    try:

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        query = """
            SELECT
                b.id,
                b.booking_date,
                b.start_time,
                b.end_time,
                b.status,
                v.vehicle_number,
                v.vehicle_type,
                p.slot_number,
                p.location
            FROM bookings b
            JOIN vehicles v ON b.vehicle_id = v.id
            JOIN parking_slots p ON b.slot_id = p.id
            WHERE b.user_id = %s
            ORDER BY b.booking_date DESC, b.created_at DESC, b.start_time DESC
        """

        cursor.execute(query, (session["user_id"],))
        bookings = cursor.fetchall()

        cursor.close()
        connection.close()

        return render_template(
            "my_bookings.html",
            bookings=bookings,
            name=session["name"]
        )

    except mysql.connector.Error as error:

        return f"""
            <h1>Database Error</h1>
            <p>{error}</p>
        """


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))


# =========================================================
# START APPLICATION
# =========================================================

if __name__ == "__main__":
    app.run(debug=True)