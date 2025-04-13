from flask import Flask, jsonify, render_template, request, redirect, url_for, session, flash
from flask_mysqldb import MySQL
import MySQLdb.cursors
import bcrypt
import re

print("[*] Initializing Flask App...")

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# Configure MySQL
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_PORT'] = 3306
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'root'
app.config['MYSQL_DB'] = 'franchise_portal'

mysql = MySQL(app)

# 🔒 Helper function to verify bcrypt format
def is_bcrypt_hash(value):
    if isinstance(value, bytes):
        value = value.decode('utf-8')
    return bool(re.match(r'^\$2[aby]?\$\d{2}\$[./A-Za-z0-9]{53}$', value))

# 🔁 Auto-insert users if not already in DB
with app.app_context():
    users = {
    "admin": "admin123",
    "franchise1": "franchise123",
    "franchise2": "franchise456"
}


    cur = mysql.connection.cursor()
    for username, password in users.items():
        role = "admin" if username == "admin" else "franchise"

        cur.execute("SELECT * FROM users WHERE username=%s", (username,))
        existing_user = cur.fetchone()

        if not existing_user:
            hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
            cur.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
                (username, hashed, role))
            print(f"[OK] User '{username}' added.")

    # Franchise Details
    cur.execute("SELECT id FROM users WHERE username=%s", ('franchise1',))
    franchise1_user = cur.fetchone()
    if franchise1_user:
        cur.execute("SELECT * FROM franchise_details WHERE user_id = %s", (franchise1_user[0],))
        if not cur.fetchone():
            cur.execute("INSERT INTO franchise_details (user_id) VALUES (%s)", (franchise1_user[0],))
            print("[OK] Franchise details added for 'franchise1'.")

    cur.execute("SELECT id FROM users WHERE username=%s", ('franchise2',))
    franchise2_user = cur.fetchone()
    if franchise2_user:
        cur.execute("SELECT * FROM franchise_details WHERE user_id = %s", (franchise2_user[0],))
        if not cur.fetchone():
            cur.execute("INSERT INTO franchise_details (user_id, id) VALUES (%s, 1002)", (franchise2_user[0],))
            print("[OK] Franchise details added for 'franchise2'.")

    mysql.connection.commit()
    cur.close()

# Home route
@app.route('/')
def home():
    return redirect(url_for('login'))

# Login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cur.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = cur.fetchone()
        cur.close()

        if user:
            stored_hash = user['password']
            if isinstance(stored_hash, str):
                stored_hash = stored_hash.encode('utf-8')

            if not is_bcrypt_hash(stored_hash):
                flash("Stored password format is invalid.", "danger")
                return redirect(url_for('login'))

            if bcrypt.checkpw(password.encode('utf-8'), stored_hash):
                session['loggedin'] = True
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['role'] = user['role']

                if user['role'] == 'franchise':
                    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
                    cur.execute("SELECT id FROM franchise_details WHERE user_id = %s", (user['id'],))
                    franchise = cur.fetchone()
                    cur.close()

                    if franchise:
                        session['franchise_id'] = franchise['id']
                        print(f"[OK] Franchise ID set: {session['franchise_id']}")
                    else:
                        flash("Franchise ID not found. Please contact support.", "danger")
                        return redirect(url_for('login'))

                    return redirect(url_for('franchise_dashboard'))

                elif user['role'] == 'admin':
                    return redirect(url_for('admin_dashboard'))
            else:
                flash("Incorrect password. Please try again.", "danger")
                return redirect(url_for('login'))
        else:
            flash("User not found. Please check your username.", "danger")
            return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/admin_dashboard')
def admin_dashboard():
    if session.get('role') == 'admin':
        cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

        # Fetch unverified students
        cur.execute("""
            SELECT s.id, s.name, s.email, s.phone, s.course, f.institution_name 
            FROM students s
            LEFT JOIN franchise_details f ON s.franchise_id = f.id
            WHERE s.verified = 0
        """)
        raw_student = cur.fetchall()
        students = [{
            'id': s['id'],
            'name': s['name'],
            'email': s['email'],
            'phone': s['phone'],
            'course': s['course'],
            'franchise': s['institution_name']
        } for s in raw_student]

        # Summary counts
        cur.execute("SELECT COUNT(*) as total FROM students WHERE verified = 1")
        total_students = cur.fetchone()['total']

        cur.execute("SELECT COUNT(*) as pending FROM students WHERE verified = 0")
        pending_count = cur.fetchone()['pending']

        cur.execute("SELECT COUNT(*) as count FROM franchise_details")
        franchise_count = cur.fetchone()['count']

        # Announcements
        cur.execute("SELECT * FROM announcements")
        announcements = cur.fetchall()

        cur.close()

        return render_template('admin_dashboard.html',
                               students=students,
                               announcements=announcements,
                               total_students=total_students,
                               pending_count=pending_count,
                               franchise_count=franchise_count)
    flash("Unauthorized access.", "danger")
    return redirect(url_for('login'))


@app.route('/all_students')
def all_students():
    cur = mysql.connection.cursor()
    cur.execute("""
    SELECT s.id, s.name, s.email, s.phone, s.course, s.total_fee, s.paid_fee,
           (s.total_fee - s.paid_fee) AS remaining_fee,
           f.institution_name 
    FROM students s
    JOIN franchise_details f ON s.franchise_id = f.id
    WHERE s.verified = 1
""")
    students = cur.fetchall()
    cur.close()
    return render_template('all_students.html', students=students)
@app.route('/pending_verifications')
def pending_verifications():
    cur = mysql.connection.cursor()

    # Get all franchises
    cur.execute("SELECT id, institution_name FROM franchise_details")
    franchises = cur.fetchall()

    # Convert to dictionary format
    franchise_list = []
    for franchise in franchises:
        franchise_id = franchise[0]
        institution_name = franchise[1]

        # Get pending students for this franchise
        cur.execute("""
            SELECT id, name, email, phone, course, total_fee, paid_fee, (total_fee - paid_fee) AS fee_remaining
            FROM students 
            WHERE verified = 0 AND franchise_id = %s
        """, (franchise_id,))
        pending_students = cur.fetchall()
        print(f"Pending for franchise {institution_name}: {pending_students}")

        # Convert student tuples to dicts
        student_dicts = []
        for stu in pending_students:
            student_dicts.append({
                'id': stu[0],
                'name': stu[1],
                'email': stu[2],
                'phone': stu[3],
                'course': stu[4],
                'total_fee': stu[5],
                'paid_fee': stu[6],
            })

        franchise_list.append({
            "id": franchise_id,
            "institution_name": institution_name,
            "students": student_dicts
        })

    cur.close()
    print("Final Franchise List:", franchise_list)  # Debug
    return render_template('pending_verifications.html', franchises=franchise_list)


@app.route('/franchise_list')
def franchise_list_view():
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Fetch all franchises with details and total students enrolled
    cur.execute("""
        SELECT f.id, f.institution_name, u.username, f.address, f.contact,
               (SELECT COUNT(*)
                FROM students s
                WHERE s.franchise_id = f.id AND s.verified = 1) AS total_students
        FROM franchise_details f
        LEFT JOIN users u ON f.user_id = u.id;
    """)
    
    franchises = cur.fetchall()

     # Convert to dictionary format correctly
    franchise_data = [
        {
            "id": franchise["id"],
            "institution_name": franchise["institution_name"],
            "username": franchise["username"],  # Corrected username placement
            "address": franchise["address"],
            "contact": franchise["contact"],
            "student_count": franchise["total_students"]
        }
        for franchise in franchises
    ]

    cur.close()
    return render_template('franchise_list.html', franchises=franchise_data)


# Franchise Dashboard
@app.route('/franchise_dashboard')
def franchise_dashboard():
    print("[DEBUG] Session Data:", session)  # Debugging Line
    if session.get('role') == 'franchise':
        cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        
        # Fetch students for this specific franchise
        franchise_id = session.get('franchise_id')
        if not franchise_id:
            flash("Error: Franchise ID not found in session. Please re-login.", "danger")
            return redirect(url_for('login'))
        cur.execute("SELECT * FROM students WHERE franchise_id = %s AND verified = 1", (franchise_id,))
        students = cur.fetchall()
        print("[DEBUG] Fetched Students:", students)  # Debugging Line
        cur.execute("SELECT * FROM announcements ORDER BY date_posted DESC")
        announcements = cur.fetchall()
        cur.close()
        return render_template('dashboard.html', students=students, announcements=announcements)
    flash("Unauthorized access.", "danger")
    return redirect(url_for('login'))

# Enrollment Page
@app.route('/enrollment', methods=['GET', 'POST'])
def enrollment():
    if 'user_id' not in session or session.get('role') != 'franchise':
        return redirect(url_for('login')) 
    franchise_id = session.get('franchise_id')
    if not franchise_id:
        flash("Franchise ID not found!", "danger")
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        # Safely access form fields
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        course = request.form.get('course')
        total_fee = request.form.get('total_fee')
        paid_fee = request.form.get('paid_fee')
        franchise_id = session.get('franchise_id')   
        
        cur = mysql.connection.cursor()
        cur.execute("INSERT INTO students (name, email, phone, course, total_fee, paid_fee,franchise_id, verified,enrollment_date) VALUES (%s, %s, %s, %s, %s, %s,%s, 0, CURRENT_DATE)", 
                (name, email, phone, course, total_fee, paid_fee,franchise_id))
        mysql.connection.commit()
        cur.close()
        flash("Student enrollment submitted for verification.", "success")

        return redirect(url_for('enrollment'))     
    # ✅ Fetch all verified students for this franchise
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT *, (total_fee - paid_fee) AS fee_remaining FROM students WHERE franchise_id = %s", (franchise_id,))


    students = cur.fetchall()
    cur.close()

    return render_template('enrollment.html', students=students)   
        
    


# View Students
@app.route('/students')
def view_students():
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT * FROM students WHERE verified = TRUE")
        students = cursor.fetchall()
        cursor.close()
        return render_template('students.html', students=students)
    except Exception as e:
        return f"Error fetching students: {e}", 500


# Verify Student (Admin)
@app.route('/verify_student/<int:student_id>', methods=['POST'])
def verify_student(student_id):
    if session.get('role') != 'admin':
        flash("Unauthorized access.", "danger")
        return redirect(url_for('login'))

    cur = mysql.connection.cursor()
    cur.execute("UPDATE students SET verified = 1 WHERE id = %s", (student_id,))
    mysql.connection.commit()
    cur.close()
    
    flash("Student verified successfully.", "success")
    return redirect(url_for('pending_verifications'))    

     
# Add Student
@app.route('/add_student', methods=['GET', 'POST'])
def add_student():
    if 'user_id' not in session:
        return redirect(url_for('login'))  # Redirect to login if not logged in

    franchise_id = session.get('franchise_id')  # Get franchise ID from session
    if not franchise_id:
        return "Error: Franchise ID not found in session. Please re-login.", 400  # Return error if missing
    
    print(f"Franchise ID from session: {franchise_id}")  # Debugging line
    
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        phone = request.form['phone']
        course = request.form['course']
        total_fee = request.form['total_fee']
        paid_fee = request.form['paid_fee']

        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        # Check if email already exists
        cursor.execute("SELECT * FROM students WHERE email = %s AND franchise_id = %s", (email, franchise_id))
        existing_student = cursor.fetchone()

        if existing_student:
            cursor.close()
            return "Error: A student with this email already exists for this franchise.", 400   # Show error message
        
        cursor.execute("""
            INSERT INTO students (name, email, phone, course, total_fee, paid_fee, franchise_id, verified) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE)
        """, (name, email, phone, course, total_fee, paid_fee, franchise_id))
        
        mysql.connection.commit()
        cursor.close()
        
        return redirect(url_for('enrollment'))  # Go back to enrollment page

    return render_template('add_student.html')  # Create a form for adding students


# Edit Student
# Edit Student
@app.route('/students/<int:student_id>/edit', methods=['GET', 'POST'])
def edit_student(student_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    franchise_id = session.get('franchise_id')  # Get franchise ID from session

    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Ensure student belongs to the logged-in franchise
    cursor.execute("SELECT * FROM students WHERE id = %s AND franchise_id = %s", (student_id, franchise_id))
    student = cursor.fetchone()

    if not student:
        return "Unauthorized", 403  # Prevents modifying other franchise’s students
    
    if request.method == 'POST':
            name = request.form['name']
            email = request.form['email']
            phone = request.form['phone']
            course = request.form['course']
            total_fee = request.form['total_fee']
            paid_fee = request.form['paid_fee']
            

            cursor.execute("""
                UPDATE students 
                SET name=%s, email=%s, phone=%s, course=%s, total_fee=%s, paid_fee=%s, verified=0
                WHERE id=%s AND franchise_id=%s
            """, (name, email, phone, course, total_fee, paid_fee,  student_id, franchise_id))
            mysql.connection.commit()
            cursor.close()
            flash("Student details updated. Awaiting admin verification.", "info")
            return redirect(url_for('enrollment'))

    cursor.close()
    return render_template('edit_student.html', student=student)    


# Delete Student
@app.route('/delete_student/<int:student_id>', methods=['POST'])
def delete_student(student_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    franchise_id = session.get('franchise_id')

    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Ensure student belongs to the logged-in franchise
    cursor.execute("SELECT * FROM students WHERE id = %s AND franchise_id = %s", (student_id, franchise_id))
    student = cursor.fetchone()

    if not student:
        return "Unauthorized", 403  # Prevent deletion of another franchise's student

    # Delete student
    cursor.execute("DELETE FROM students WHERE id=%s AND franchise_id=%s", (student_id, franchise_id))
    mysql.connection.commit()
    cursor.close()

    return redirect(url_for('enrollment'))

    
    
# Announcements Route
@app.route('/announcements', methods=['GET', 'POST'])
def announcements():
    if request.method == 'POST':
        title = request.form.get('announcement_title')  # Get title from form
        message = request.form.get('announcement_message')  # Get message from form
        
        if title and message:
            cur = mysql.connection.cursor()
            cur.execute("INSERT INTO announcements (title, message, date_posted) VALUES (%s, %s, NOW())", 
                        (title, message))  
            mysql.connection.commit()
            cur.close()
            flash("Announcement added successfully!", "success")
            return redirect(url_for('announcements'))

    # Fetch announcements
    cur = mysql.connection.cursor()
    cur.execute("SELECT id, title, message, date_posted FROM announcements ORDER BY date_posted DESC")
    announcements = cur.fetchall()
    cur.close()

    return render_template('announcement.html', announcements=announcements)
    

@app.route('/add_announcement', methods=['POST'])
def add_announcement():
    if 'role' in session and session['role'] == 'admin':  # Only admin can add announcements
        data = request.get_json()
        title = data.get("title")
        message = data.get("message")

        if title and message:
            cur = mysql.connection.cursor()
            cur.execute("INSERT INTO announcements (title, message, date_posted) VALUES (%s, %s, NOW())",
                        (title, message))
            mysql.connection.commit()
            cur.close()
            return jsonify({"success": True})
    
    return jsonify({"success": False})


# Mark Announcement as Read
@app.route('/mark_announcement_read', methods=['POST'])
def mark_announcement_read():
    franchise_id = session.get('franchise_id')
    announcement_id = request.json.get('announcement_id')
    
    if not franchise_id:
        return jsonify({"error": "Unauthorized"}), 403
    
    cursor = mysql.connection.cursor()
    cursor.execute("""
        INSERT INTO franchise_announcements (franchise_id, announcement_id, is_read)
        VALUES (%s, %s, TRUE)
        ON DUPLICATE KEY UPDATE is_read = TRUE
    """, (franchise_id, announcement_id))
    mysql.connection.commit()
    cursor.close()
    
    return jsonify({"message": "Announcement marked as read"})

@app.before_request
def delete_old_announcements():
    try:
        cursor = mysql.connection.cursor()
        cursor.execute("""
            DELETE FROM announcements 
            WHERE date_posted < NOW() - INTERVAL 30 DAY
        """)
        mysql.connection.commit()
        cursor.close()
        print("[*] Old announcements deleted successfully!")
    except MySQLdb.Error as e:
        print(f"[X] MySQL Error: {e}")


# Track read announcements
def get_unread_count(franchise_id):
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("""
        SELECT COUNT(*) AS unread_count 
        FROM announcements a
        LEFT JOIN franchise_announcements fa 
        ON a.id = fa.announcement_id AND fa.franchise_id = %s
        WHERE fa.announcement_id IS NULL
    """, (franchise_id,))
    result = cursor.fetchone()
    cursor.close()
    return result['unread_count'] if result else 0




@app.route('/get_unread_announcements')
def get_unread_announcements():
    franchise_id = session.get('franchise_id')  # Example session
    if not franchise_id:
        return jsonify({"error": "Unauthorized access"}), 403
    
    conn = mysql.connect(host='localhost', user='root', password='', database='your_db')
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT a.id, a.title, a.message, a.date_posted 
        FROM announcements a
        JOIN franchise_announcements fa ON a.id = fa.announcement_id
        WHERE fa.franchise_id = %s AND fa.is_read = FALSE
    """, (franchise_id,))
    
    announcements = cursor.fetchall()
    conn.close()

    return jsonify({"unread_announcements": announcements})

# Home Page with Franchise Details
@app.route('/franchise_home')
def franchise_home():
    if 'loggedin' not in session or session.get('role') != 'franchise':
        flash("Unauthorized access. Please log in.", "danger")
        return redirect(url_for('login'))

    franchise_id = session.get('franchise_id')
    
    if not franchise_id:
        flash("Error: Franchise ID not found in session. Please re-login.", "danger")
        return redirect(url_for('login'))

    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    # Fetch details for the logged-in franchise
    cursor.execute("SELECT * FROM franchise_details WHERE id = %s", (franchise_id,))
    franchise = cursor.fetchone()
    
    cursor.close()

    if not franchise:
        flash("Error: Franchise details not found.", "danger")
        return redirect(url_for('login'))

    return render_template('home.html', franchise=franchise)


# Get Student Enrollment Count Based on Month
@app.route('/get_student_count')
def get_student_count():
    selected_month = request.args.get('month')
    
    if not selected_month:
        return jsonify({"error": "No month selected"}), 400

    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT COUNT(*) as count FROM students WHERE MONTH(enrollment_date) = %s", (selected_month,))
    result = cursor.fetchone()
    cursor.close()
    
    student_count = result['count'] if result and 'count' in result else 0
    print(f"[] SQL Query: SELECT COUNT() FROM students WHERE month = '{selected_month}'")
    print(f"[*] Selected Month: {selected_month}, Student Count: {student_count}")  # Debugging

    return jsonify({"count": student_count})

@app.route('/other_franchises')
def other_franchises():
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Get franchise details excluding the logged-in franchise
    cur.execute("""
        SELECT f.id, f.institution_name, COALESCE(COUNT(s.id), 0) AS student_count 
        FROM franchise_details f
        LEFT JOIN students s ON f.id = s.franchise_id
        WHERE f.id != %s  -- Exclude the logged-in franchise
        GROUP BY f.id, f.institution_name
    """, (session['franchise_id'],))  # Assuming franchise_id is stored in session
    
    franchises = cur.fetchall()
    cur.close()
    
    return render_template('other_franchises.html', franchises=franchises)

@app.route('/fees_status')
def fees_status():
    # Ensure the franchise is logged in
    if 'franchise_id' not in session:
        return redirect(url_for('franchise_login'))

    franchise_id = session['franchise_id']

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Fetch students enrolled under this franchise
    cur.execute("""
        SELECT id, name, email, phone, course, total_fee, paid_fee 
        FROM students 
        WHERE franchise_id = %s
    """, (franchise_id,))

    students = cur.fetchall()
    cur.close()

    return render_template('fees_status.html', students=students)



if __name__ == '__main__':  # Correct
    print("[*] Starting Flask app on port 5001...")
    app.run(debug=True, port=5001)







