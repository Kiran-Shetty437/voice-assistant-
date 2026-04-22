import sqlite3
import json
import os

def insert_data():
    json_path = "students.json"
    db_path = "database.db"
    
    if not os.path.exists(json_path):
        print(f"Error: {json_path} not found.")
        return
        
    with open(json_path, 'r') as f:
        students = json.load(f)
        
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    # Empty existing students to avoid conflicts if desired, 
    # but here we'll just try to insert and skip duplicates.
    
    count = 0
    skipped = 0
    
    for s in students:
        # Default password = roll number
        # Section = empty string (as per previous rules)
        # Photo = None
        params = (
            s['name'], 
            s['roll'], 
            s['roll'], # password
            s['course'], 
            "", # section
            None, # photo
            s.get('phone', ''), 
            s.get('email', '')
        )
        
        try:
            cur.execute("""
                INSERT INTO students (name, roll_number, password, course, section, photo, phone, email)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, params)
            count += 1
        except sqlite3.IntegrityError:
            skipped += 1
            
    conn.commit()
    conn.close()
    print(f"Insertion completed. Added {count} students, skipped {skipped} duplicates.")

if __name__ == "__main__":
    insert_data()
