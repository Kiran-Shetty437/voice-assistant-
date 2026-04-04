from flask import Flask, render_template, request, redirect, url_for, flash, session
import sqlite3
import os
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import threading
import time

app = Flask(__name__)
app.secret_key = "super_secret_key"

# ---------------- EMAIL HELPER FUNCTION ----------------
def send_email(to_email, subject, body, is_html=False):
    SENDER_EMAIL = "uniplace.portal@gmail.com"
    APP_PASSWORD = "schaulheewxzpqjh"

    try:
        msg = MIMEText(body, "html" if is_html else "plain")
        msg["Subject"] = subject
        msg["From"] = f"CareerConnect <{SENDER_EMAIL}>"
        msg["To"] = to_email

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(SENDER_EMAIL, APP_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Failed to send email to {to_email}: {e}")
        return False

# ----------------ADMIN LOGIN----------------
ADMIN_CREDENTIALS = {
    "admin": "123"
}

# ---------------- DATABASE CONNECTION ----------------
def get_db():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn

# ---------------- CREATE TABLE ----------------
def create_table():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            roll_number TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            course TEXT NOT NULL,
            section TEXT NOT NULL
        )
    """)
    cur.execute("PRAGMA table_info(students)")
    columns = [col[1] for col in cur.fetchall()]
    if "photo" not in columns:
        cur.execute("ALTER TABLE students ADD COLUMN photo TEXT")
    if "phone" not in columns:
        cur.execute("ALTER TABLE students ADD COLUMN phone TEXT")
    if "email" not in columns:
        cur.execute("ALTER TABLE students ADD COLUMN email TEXT")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            about TEXT NOT NULL,
            end_date TEXT
        )
    """)
    cur.execute("PRAGMA table_info(companies)")
    columns = [col[1] for col in cur.fetchall()]
    if "end_date" not in columns:
        cur.execute("ALTER TABLE companies ADD COLUMN end_date TEXT")
    if "reminder_sent" not in columns:
        cur.execute("ALTER TABLE companies ADD COLUMN reminder_sent INTEGER DEFAULT 0")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            company_id INTEGER NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id),
            FOREIGN KEY (company_id) REFERENCES companies(id)
        )
    """)
    conn.commit()
    conn.close()

create_table()

# ---------------- LOGIN ----------------
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user_type = request.form.get('user_type')

        # -------- ADMIN LOGIN --------
        if user_type == 'admin':
            username = request.form.get('username')
            password = request.form.get('password')

            if ADMIN_CREDENTIALS.get(username) == password:
                session['admin'] = username
                return redirect(url_for('admin_dashboard'))
            else:
                flash("Invalid Admin Credentials!", "error")

        # -------- STUDENT LOGIN --------
        elif user_type == 'student':
            reg_no = request.form.get('reg_no')
            password = request.form.get('password')

            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM students WHERE roll_number=? AND password=?",
                (reg_no, password)
            )
            student = cur.fetchone()
            conn.close()

            if student:
                session['student_id'] = student['id']
                return redirect(url_for('student_profile'))
            else:
                flash("Invalid Registration Number or Password!", "error")

        return redirect(url_for('login'))

    return render_template('login.html')


# ---------------- ADMIN DASHBOARD ----------------
@app.route('/admin_dashboard')
def admin_dashboard():
    if 'admin' not in session:
        return redirect(url_for('login'))
        
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM students")
    students = cur.fetchall()

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cur.execute("SELECT * FROM companies WHERE end_date >= ? OR end_date IS NULL", (now_str,))
    companies = cur.fetchall()

    cur.execute("""
        SELECT s.name as student_name, s.roll_number, c.name as company_name, 
               datetime(a.applied_at, 'localtime') as applied_at 
        FROM applications a
        JOIN students s ON a.student_id = s.id
        JOIN companies c ON a.company_id = c.id
        ORDER BY a.applied_at DESC
    """)
    applications = cur.fetchall()

    total_students = len(students)
    total_companies = len(companies)
    total_applications = len(applications)

    # Chart 1: Applications Over Time (Last 7 Days)
    cur.execute("""
        SELECT date(applied_at, 'localtime') as app_date, COUNT(*) as count 
        FROM applications 
        GROUP BY date(applied_at, 'localtime') 
        ORDER BY app_date DESC LIMIT 7
    """)
    apps_by_date = cur.fetchall()
    apps_by_date = sorted([dict(row) for row in apps_by_date], key=lambda x: x['app_date'])
    
    # Chart 2: Students By Course
    cur.execute("SELECT course, COUNT(*) as count FROM students GROUP BY course")
    students_by_course = [dict(row) for row in cur.fetchall()]

    # Chart 3: Applications By Company
    cur.execute("""
        SELECT c.name, COUNT(a.id) as count 
        FROM companies c 
        LEFT JOIN applications a ON c.id = a.company_id 
        GROUP BY c.id 
        ORDER BY count DESC LIMIT 5
    """)
    apps_by_company = [dict(row) for row in cur.fetchall()]

    conn.close()
    
    return render_template('admin_dashboard.html', 
                           students=students, 
                           applications=applications,
                           total_students=total_students,
                           total_companies=total_companies,
                           total_applications=total_applications,
                           apps_by_date=apps_by_date,
                           students_by_course=students_by_course,
                           apps_by_company=apps_by_company)


# -------------- ADMIN STUDENTS PAGE --------------
@app.route('/admin_students')
def admin_students():
    if 'admin' not in session:
        return redirect(url_for('login'))
        
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM students")
    students = cur.fetchall()
    conn.close()
    return render_template('admin_students.html', students=students)


# ---------------- ADMIN COMPANIES PAGE ----------------
@app.route('/admin_companies')
def admin_companies():
    if 'admin' not in session:
        return redirect(url_for('login'))
        
    conn = get_db()
    cur = conn.cursor()
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cur.execute("SELECT * FROM companies WHERE end_date >= ? OR end_date IS NULL", (now_str,))
    companies = cur.fetchall()
    conn.close()
    
    return render_template('admin_companies.html', companies=companies)


# ---------------- ADD STUDENT ----------------
@app.route('/add_student', methods=['GET', 'POST'])
def add_student():
    if 'admin' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        name = request.form['name']
        roll = request.form['roll_number']
        course = request.form['course']
        section = request.form['section']

        phone = request.form.get('phone')
        email = request.form.get('email')

        password = roll  # Default password
        
        photo = request.files.get('photo')
        photo_filename = None
        if photo and photo.filename:
            filename = secure_filename(photo.filename)
            upload_folder = os.path.join(app.root_path, 'static', 'uploads')
            os.makedirs(upload_folder, exist_ok=True)
            photo_path = os.path.join(upload_folder, filename)
            photo.save(photo_path)
            photo_filename = filename

        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO students (name, roll_number, password, course, section, photo, phone, email)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, roll, password, course, section, photo_filename, phone, email))
            conn.commit()
            conn.close()

            if email:
                subject = "Welcome to CareerConnect!"
                body = f"Hello {name},\n\nYour account has been created.\nYour Roll Number is: {roll}\nYour Default Password is: {password}\n\nPlease login and update your profile."
                send_email(email, subject, body)

            flash("Student Added Successfully!", "success")
            return redirect(url_for('admin_dashboard'))

        except sqlite3.IntegrityError:
            flash("Roll Number Already Exists!", "error")

    return render_template('add_student.html')


# ---------------- EDIT STUDENT ----------------
@app.route('/edit_student/<int:id>', methods=['GET', 'POST'])
def edit_student(id):
    if 'admin' not in session:
        return redirect(url_for('login'))

    conn = get_db()
    cur = conn.cursor()

    if request.method == 'POST':
        name = request.form['name']
        roll = request.form['roll_number']
        course = request.form['course']
        section = request.form['section']
        phone = request.form.get('phone')
        email = request.form.get('email')

        # Photo handling
        photo = request.files.get('photo')
        if photo and photo.filename:
            filename = secure_filename(photo.filename)
            upload_folder = os.path.join(app.root_path, 'static', 'uploads')
            os.makedirs(upload_folder, exist_ok=True)
            photo_path = os.path.join(upload_folder, filename)
            photo.save(photo_path)
            
            cur.execute("""
                UPDATE students SET name=?, roll_number=?, course=?, section=?, phone=?, email=?, photo=? WHERE id=?
            """, (name, roll, course, section, phone, email, filename, id))
        else:
            cur.execute("""
                UPDATE students SET name=?, roll_number=?, course=?, section=?, phone=?, email=? WHERE id=?
            """, (name, roll, course, section, phone, email, id))
            
        conn.commit()
        conn.close()
        flash("Student Updated Successfully!", "success")
        return redirect(url_for('admin_students'))

    cur.execute("SELECT * FROM students WHERE id=?", (id,))
    student = cur.fetchone()
    conn.close()
    
    if not student:
        flash("Student not found", "error")
        return redirect(url_for('admin_students'))
        
    return render_template('edit_student.html', student=student)


# ---------------- DELETE STUDENT ----------------
@app.route('/delete_student/<int:id>', methods=['POST'])
def delete_student(id):
    if 'admin' not in session:
        return redirect(url_for('login'))

    conn = get_db()
    cur = conn.cursor()
    # Also delete applications if any
    cur.execute("DELETE FROM applications WHERE student_id=?", (id,))
    cur.execute("DELETE FROM students WHERE id=?", (id,))
    conn.commit()
    conn.close()
    
    flash("Student Deleted Successfully!", "success")
    return redirect(url_for('admin_students'))


# ---------------- STUDENT PROFILE ----------------
@app.route('/student_profile')
def student_profile():
    if 'student_id' not in session:
        return redirect(url_for('login'))

    student_id = session['student_id']

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM students WHERE id=?", (student_id,))
    student = cur.fetchone()

    now = datetime.now()
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')
    cur.execute("SELECT * FROM companies WHERE end_date >= ? OR end_date IS NULL", (now_str,))
    companies_raw = cur.fetchall()
    conn.close()

    companies = []
    for c in companies_raw:
        c_dict = dict(c)
        if c_dict.get('end_date'):
            ed_str = c_dict['end_date'].replace('T', ' ')
            if len(ed_str) == 16:
                ed_str += ':00'
            try:
                try:
                    end_dt = datetime.strptime(ed_str, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    end_dt = datetime.strptime(ed_str, '%Y-%m-%d')
                
                diff = end_dt - now
                if timedelta(0) < diff <= timedelta(hours=24):
                    c_dict['show_timer'] = True
                    c_dict['end_timestamp'] = end_dt.timestamp() * 1000
            except ValueError:
                pass
        companies.append(c_dict)

    return render_template('student_profile.html', student=student, companies=companies)


# ---------------- EDIT MY PROFILE ----------------
@app.route('/edit_my_profile', methods=['GET', 'POST'])
def edit_my_profile():
    if 'student_id' not in session:
        return redirect(url_for('login'))

    student_id = session['student_id']
    conn = get_db()
    cur = conn.cursor()

    if request.method == 'POST':
        phone = request.form.get('phone')
        email = request.form.get('email')

        try:
            cur.execute("""
                UPDATE students SET phone=?, email=? WHERE id=?
            """, (phone, email, student_id))
            conn.commit()
            flash("Profile Updated Successfully!", "success")
            return redirect(url_for('student_profile'))
        except Exception as e:
            flash("Update failed, please try again.", "error")
        finally:
            conn.close()

    cur.execute("SELECT * FROM students WHERE id=?", (student_id,))
    student = cur.fetchone()
    conn.close()

    return render_template('edit_my_profile.html', student=student)


# ---------------- RESUME BUILDER ----------------
@app.route('/resume_builder')
def resume_builder():
    if 'student_id' not in session:
        return redirect(url_for('login'))
    return render_template('resume_templates.html')

@app.route('/resume_builder/<template_id>')
def edit_resume(template_id):
    if 'student_id' not in session:
        return redirect(url_for('login'))
    
    student_id = session['student_id']
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM students WHERE id=?", (student_id,))
    student = cur.fetchone()
    conn.close()

    return render_template('edit_resume.html', template_id=template_id, student=student)


# ---------------- LOGOUT ----------------
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ---------------- APPLY TO COMPANY ----------------
@app.route('/apply/<int:company_id>')
def apply_company(company_id):
    if 'student_id' not in session:
        return redirect(url_for('login'))
        
    student_id = session['student_id']
    
    conn = get_db()
    cur = conn.cursor()
    
    # Track the application if it hasn't been tracked yet
    cur.execute("SELECT id FROM applications WHERE student_id=? AND company_id=?", (student_id, company_id))
    if not cur.fetchone():
        cur.execute("INSERT INTO applications (student_id, company_id) VALUES (?, ?)", (student_id, company_id))
        conn.commit()
    
    cur.execute("SELECT url FROM companies WHERE id=?", (company_id,))
    company = cur.fetchone()
    conn.close()
    
    if company:
        return redirect(company['url'])
        
    return redirect(url_for('student_profile'))


# ---------------- ADD COMPANY ----------------
@app.route('/add_company', methods=['GET', 'POST'])
def add_company():
    if 'admin' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        name = request.form['name']
        url = request.form['url']
        about = request.form['about']
        end_date = request.form.get('end_date')

        end_date_str = None
        if end_date:
            if len(end_date) == 10:
                end_date_str = f"{end_date} 23:59:59"
            else:
                end_date_str = end_date.replace('T', ' ')

        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO companies (name, url, about, end_date)
                VALUES (?, ?, ?, ?)
            """, (name, url, about, end_date_str))
            
            cur.execute("SELECT email FROM students WHERE email IS NOT NULL AND email != ''")
            student_records = cur.fetchall()
            student_emails = [row['email'] for row in student_records]
            
            conn.commit()
            conn.close()

            subject = f"New Company Alert: {name}"
            body = f"Hello Student,\n\nA new company ({name}) is now accepting applications on CareerConnect!\n\nCheck your dashboard for details."
            
            for stu_email in student_emails:
                send_email(stu_email, subject, body)

            flash("Company details saved successfully!", "success")
            return redirect(url_for('admin_companies'))

        except Exception as e:
            flash("Not successful, please try again.", "error")

    return render_template('add_company.html')


# ---------------- EDIT COMPANY ----------------
@app.route('/edit_company/<int:id>', methods=['GET', 'POST'])
def edit_company(id):
    if 'admin' not in session:
        return redirect(url_for('login'))

    conn = get_db()
    cur = conn.cursor()

    if request.method == 'POST':
        name = request.form['name']
        url = request.form['url']
        about = request.form['about']
        end_date = request.form.get('end_date')

        end_date_str = None
        if end_date:
            if len(end_date) == 10:
                end_date_str = f"{end_date} 23:59:59"
            else:
                end_date_str = end_date.replace('T', ' ')

        try:
            cur.execute("""
                UPDATE companies SET name=?, url=?, about=?, end_date=? WHERE id=?
            """, (name, url, about, end_date_str, id))
            conn.commit()
            flash("Company Updated Successfully!", "success")
            return redirect(url_for('admin_companies'))
        except Exception as e:
            flash("Update failed, please try again.", "error")
        finally:
            conn.close()

    cur.execute("SELECT * FROM companies WHERE id=?", (id,))
    company = cur.fetchone()
    conn.close()
    
    if not company:
        flash("Company not found", "error")
        return redirect(url_for('admin_companies'))
        
    return render_template('edit_company.html', company=company)


# ---------------- DELETE COMPANY ----------------
@app.route('/delete_company/<int:id>', methods=['POST'])
def delete_company(id):
    if 'admin' not in session:
        return redirect(url_for('login'))

    conn = get_db()
    cur = conn.cursor()
    # Delete applications related to this company first to maintain constraints
    cur.execute("DELETE FROM applications WHERE company_id=?", (id,))
    cur.execute("DELETE FROM companies WHERE id=?", (id,))
    conn.commit()
    conn.close()
    
    flash("Company Deleted Successfully!", "success")
    return redirect(url_for('admin_companies'))


# ---------------- REMINDER BACKGROUND THREAD ----------------
def reminder_worker():
    while True:
        try:
            conn = get_db()
            cur = conn.cursor()
            now = datetime.now()
            
            # Find companies with an end date and where we haven't sent a reminder yet
            cur.execute("SELECT * FROM companies WHERE end_date IS NOT NULL AND reminder_sent = 0")
            companies = cur.fetchall()
            
            for comp in companies:
                c_dict = dict(comp)
                ed_str = c_dict['end_date'].replace('T', ' ')
                if len(ed_str) == 16:
                    ed_str += ':00'
                    
                try:
                    try:
                        end_dt = datetime.strptime(ed_str, '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        end_dt = datetime.strptime(ed_str, '%Y-%m-%d')
                        
                    diff = end_dt - now
                    if timedelta(0) < diff <= timedelta(hours=24):
                        days = diff.days
                        hours, remainder = divmod(diff.seconds, 3600)
                        minutes, seconds = divmod(remainder, 60)
                        
                        cur.execute("SELECT email FROM students WHERE email IS NOT NULL AND email != ''")
                        students = cur.fetchall()
                        student_emails = [s['email'] for s in students]
                        
                        subject = f"Urgent: {c_dict['name']} closing in less than 24 hours!"
                        
                        html_body = f"""
                        <div style="background-color: #ffda03; padding: 40px 20px; text-align: center; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; border-radius: 8px;">
                            <h1 style="color: #212135; margin-bottom: 10px; font-size: 28px;">Limited time offer</h1>
                            <p style="color: #4a4a4a; font-size: 18px; margin-bottom: 30px;">This application is available only for next...</p>
                            
                            <div style="margin-bottom: 30px;">
                                <div style="display: inline-block; text-align: center; margin: 0 10px; color: #212135;">
                                    <div style="font-size: 24px; font-weight: bold;">{days}</div>
                                    <div style="font-size: 14px;">Days</div>
                                </div>
                                <div style="display: inline-block; font-size: 24px; vertical-align: top; margin-top: 5px; color: #212135;">:</div>
                                <div style="display: inline-block; text-align: center; margin: 0 10px; color: #212135;">
                                    <div style="font-size: 24px; font-weight: bold;">{hours}</div>
                                    <div style="font-size: 14px;">Hours</div>
                                </div>
                                <div style="display: inline-block; font-size: 24px; vertical-align: top; margin-top: 5px; color: #212135;">:</div>
                                <div style="display: inline-block; text-align: center; margin: 0 10px; color: #212135;">
                                    <div style="font-size: 24px; font-weight: bold;">{minutes}</div>
                                    <div style="font-size: 14px;">Min</div>
                                </div>
                                <div style="display: inline-block; font-size: 24px; vertical-align: top; margin-top: 5px; color: #212135;">:</div>
                                <div style="display: inline-block; text-align: center; margin: 0 10px; color: #212135;">
                                    <div style="font-size: 24px; font-weight: bold;">{seconds}</div>
                                    <div style="font-size: 14px;">Sec</div>
                                </div>
                            </div>
                        
                            <p style="font-size: 18px; margin-bottom: 30px; color: #212135;"><strong>Company:</strong> {c_dict['name']}</p>
                        
                            <a href="{c_dict['url']}" style="display: inline-block; background-color: #212135; color: #ffffff; text-decoration: none; padding: 15px 50px; border-radius: 30px; font-size: 18px; font-weight: bold;">Show me</a>
                        </div>
                        """
                        
                        for stu_email in student_emails:
                            send_email(stu_email, subject, html_body, is_html=True)
                            
                        # Mark as sent
                        cur.execute("UPDATE companies SET reminder_sent = 1 WHERE id = ?", (c_dict['id'],))
                        conn.commit()
                        
                except Exception as e:
                    pass
            
            conn.close()
        except Exception as e:
            pass
            
        time.sleep(60)

# Start the thread safely
thread = threading.Thread(target=reminder_worker, daemon=True)
thread.start()

if __name__ == '__main__':
    app.run(debug=True)