import re
from flask import Flask, request, render_template, jsonify, session, redirect, url_for
import mysql.connector
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your_secret_session_key'


# --- Helper Functions (Replicating your PHP includes) ---
def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="immersiotrack"
    )


def get_current_user_id():
    return session.get('user_id', 1)  # Mocking admin ID


def get_current_user_name():
    return session.get('user_name', 'Admin User')


def get_unread_notifications_count(conn, user_id):
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM notifications WHERE user_id = %s AND is_read = 0", (user_id,))
    return cursor.fetchone()[0]


# --- Main Route ---
@app.route('/establishments', methods=['GET', 'POST'])
def establishments():
    # requireRole('admin') logic check
    if session.get('role') != 'admin' and not app.debug:
        return "Unauthorized", 403

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    admin_id = get_current_user_id()

    # Fetch Notifications
    unread_notifications = get_unread_notifications_count(conn, admin_id)
    cursor.execute("SELECT * FROM notifications WHERE user_id = %s ORDER BY created_at DESC LIMIT 10", (admin_id,))
    notifications = cursor.fetchall()

    message = ''
    error = ''
    is_ajax_request = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    # ── POST Actions ──────────────────────────────────────────────────────────────
    if request.method == 'POST':
        action = request.form.get('action', '')

        if action in ['add', 'edit']:
            name = request.form.get('name', '').strip()
            company_type = request.form.get('company_type', '').strip()
            contact_number = request.form.get('contact_number', '').strip()
            email = request.form.get('email', '').strip()
            address = request.form.get('address', '').strip()
            city = request.form.get('city', '').strip()
            supervisor_name = request.form.get('supervisor_name', '').strip()
            supervisor_pos = request.form.get('supervisor_position', '').strip()
            supervisor_contact = request.form.get('supervisor_contact', '').strip()

            try:
                latitude = float(request.form.get('latitude')) if request.form.get('latitude') else None
                longitude = float(request.form.get('longitude')) if request.form.get('longitude') else None
            except ValueError:
                latitude, longitude = None, None

            try:
                radius = int(request.form.get('radius')) if request.form.get('radius') else 50
            except ValueError:
                radius = 50

            try:
                capacity = max(0, int(request.form.get('capacity', 0)))
            except ValueError:
                capacity = 0

            status_input = request.form.get('status', 'Active')
            status = status_input if status_input in ['Active', 'Inactive', 'Full'] else 'Active'
            is_add_action = (action == 'add')

            # Validate contact numbers (Philippine format: 09XXXXXXXXX)
            phone_pattern = re.compile(r'^09\d{9}$')
            gmail_pattern = re.compile(r'^[a-z0-9._%+\-]+@gmail\.com$', re.IGNORECASE)
            name_pattern = re.compile(r"^[a-zA-ZÀ-ÿ\s'\-\.]{2,}$")

            if not name:
                error = 'Company name is required.'
            elif is_add_action and not contact_number:
                error = 'Establishment contact number is required when adding a new establishment.'
            elif is_add_action and not email:
                error = 'Establishment email is required when adding a new establishment.'
            elif is_add_action and not supervisor_name:
                error = 'Supervisor name is required when adding a new establishment.'
            elif is_add_action and not supervisor_contact:
                error = 'Supervisor contact number is required when adding a new establishment.'
            elif contact_number and not phone_pattern.match(contact_number):
                error = 'Establishment contact number must be 11 digits starting with 09 (e.g., 09XXXXXXXXX). No letters allowed.'
            elif supervisor_contact and not phone_pattern.match(supervisor_contact):
                error = 'Supervisor contact number must be 11 digits starting with 09 (e.g., 09XXXXXXXXX). No letters allowed.'
            elif not (10 <= radius <= 100):
                error = 'Allowed radius must be between 10 and 100 meters.'
            elif supervisor_name and not name_pattern.match(supervisor_name):
                error = 'Supervisor name must contain letters only (no numbers or symbols).'
            elif email and not gmail_pattern.match(email):
                error = 'Establishment email must be a valid Gmail address and end with @gmail.com.'
            elif not city:
                error = 'City is required.'
            elif not address:
                error = 'Address is required.'
            else:
                # Check for duplicate establishment name
                if action == 'add':
                    cursor.execute("SELECT id FROM partner_establishments WHERE LOWER(name) = LOWER(%s)", (name,))
                    if cursor.fetchone():
                        error = 'An establishment with this name already exists. Please use a different name.'
                else:
                    est_id = int(request.form.get('est_id', 0))
                    cursor.execute("SELECT id FROM partner_establishments WHERE LOWER(name) = LOWER(%s) AND id != %s",
                                   (name, est_id))
                    if cursor.fetchone():
                        error = 'An establishment with this name already exists. Please use a different name.'

                if not error:
                    if action == 'add':
                        sql = """INSERT INTO partner_establishments 
                                 (name, company_type, contact_number, email, address, city, supervisor_name, 
                                 supervisor_position, supervisor_contact, latitude, longitude, radius, capacity, status) 
                                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
                        val = (name, company_type, contact_number, email, address, city, supervisor_name,
                               supervisor_pos, supervisor_contact, latitude, longitude, radius, capacity, status)
                        cursor.execute(sql, val)
                        conn.commit()
                        message = 'Establishment added successfully.'
                    else:
                        sql = """UPDATE partner_establishments 
                                 SET name=%s, company_type=%s, contact_number=%s, email=%s, address=%s, city=%s, 
                                 supervisor_name=%s, supervisor_position=%s, supervisor_contact=%s, latitude=%s, 
                                 longitude=%s, radius=%s, capacity=%s, status=%s WHERE id=%s"""
                        val = (name, company_type, contact_number, email, address, city, supervisor_name,
                               supervisor_pos, supervisor_contact, latitude, longitude, radius, capacity, status,
                               est_id)
                        cursor.execute(sql, val)
                        conn.commit()
                        message = 'Establishment updated successfully.'

        elif action == 'toggle_status':
            est_id = int(request.form.get('est_id', 0))
            target_status = request.form.get('target_status', '')

            if est_id <= 0:
                error = 'Invalid establishment selected.'
            elif target_status not in ['Active', 'Inactive']:
                error = 'Invalid status action.'
            else:
                cursor.execute("UPDATE partner_establishments SET status = %s WHERE id = %s", (target_status, est_id))
                conn.commit()
                message = 'Establishment activated successfully.' if target_status == 'Active' else 'Establishment deactivated successfully.'

            if is_ajax_request:
                if error:
                    return jsonify({'success': False, 'message': error}), 400
                else:
                    return jsonify({
                        'success': True,
                        'message': message,
                        'status': target_status,
                        'est_id': est_id
                    })

    # ── Fetch all establishments ──────────────────────────────────────────────────
    cursor.execute("""
        SELECT pe.*,
               (SELECT COUNT(*) FROM assignments a WHERE a.establishment_id = pe.id) AS student_count
        FROM partner_establishments pe
        ORDER BY pe.name ASC
    """)
    establishments = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('establishments.html',
                           establishments=establishments,
                           notifications=notifications,
                           unread_notifications=unread_notifications,
                           message=message,
                           error=error,
                           current_user_name=get_current_user_name())


if __name__ == '__main__':
    app.run(debug=True)