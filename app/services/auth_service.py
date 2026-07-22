import os
import sqlite3
import base64
from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'opshub.db')
SECRET_SALT = b"opshub_salt_2026"

def _get_cipher():
    # Derive a 32-byte key from our session secret key for symmetric encryption
    key_source = b"opshub_secure_session_key_2026"
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=SECRET_SALT,
        iterations=100000
    )
    key = base64.urlsafe_b64encode(kdf.derive(key_source))
    return Fernet(key)

def encrypt_val(val):
    if not val:
        return None
    f = _get_cipher()
    return f.encrypt(val.encode('utf-8')).decode('utf-8')

def decrypt_val(val_enc):
    if not val_enc:
        return None
    f = _get_cipher()
    try:
        return f.decrypt(val_enc.encode('utf-8')).decode('utf-8')
    except Exception:
        return None

def get_db_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create users table with RBAC and AD fields
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            ad_user TEXT,
            ad_password_encrypted TEXT
        )
    ''')

    # Create execution_logs table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS execution_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            ticket_number TEXT NOT NULL,
            execution_type TEXT NOT NULL,
            target_vm TEXT,
            inventory_used TEXT,
            playbook_or_command TEXT,
            status TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT,
            duration REAL,
            log_file TEXT
        )
    ''')

    # Create audit_events table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            actor_username TEXT NOT NULL,
            action_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            details TEXT
        )
    ''')
    
    # Database migration check: check and add missing columns for existing table
    cursor.execute("PRAGMA table_info(users)")
    columns = [row[1] for row in cursor.fetchall()]
    if columns:
        if 'email' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN email TEXT")
        if 'status' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN status TEXT DEFAULT 'Approved'")
        if 'ad_user' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN ad_user TEXT")
        if 'ad_password_encrypted' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN ad_password_encrypted TEXT")
        
        # Standardize old 'Administrator' roles to 'Admin'
        cursor.execute("UPDATE users SET role = 'Admin' WHERE role = 'Administrator'")
        conn.commit()
    
    # Seed a static administrator user if empty
    cursor.execute('SELECT COUNT(*) FROM users')
    if cursor.fetchone()[0] == 0:
        default_user = "admin"
        default_email = "admin@opshub.local"
        default_pass = "admin123"
        hashed_pass = generate_password_hash(default_pass)
        
        cursor.execute(
            'INSERT INTO users (username, email, password_hash, role, status) VALUES (?, ?, ?, ?, ?)',
            (default_user, default_email, hashed_pass, "Admin", "Approved")
        )
        conn.commit()
        print(f"[AUTH SERVICE] Seeded static user: '{default_user}' with password: '{default_pass}'")
        
    conn.close()

def authenticate_user(username, password):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Support signing in using either username or email
    cursor.execute('SELECT * FROM users WHERE username = ? OR email = ?', (username.strip(), username.strip()))
    user = cursor.fetchone()
    conn.close()
    
    if user and check_password_hash(user['password_hash'], password):
        if user['status'] != 'Approved':
            # Return status inside a dictionary wrapper to signal unapproved state
            return {"error": f"Your account status is currently '{user['status']}'. Please contact your administrator."}
            
        return {
            "id": user['id'],
            "username": user['username'],
            "email": user['email'],
            "role": user['role'],
            "status": user['status']
        }
    return None

def register_user(username, email, password):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check for duplicates programmatically to enforce uniqueness
        cursor.execute('SELECT 1 FROM users WHERE username = ? OR email = ?', (username.strip(), email.strip()))
        if cursor.fetchone():
            return False, "Username or Email already registered."

        hashed = generate_password_hash(password)
        cursor.execute(
            'INSERT INTO users (username, email, password_hash, role, status) VALUES (?, ?, ?, ?, ?)',
            (username.strip(), email.strip(), hashed, 'User', 'Pending')
        )
        conn.commit()
        return True, "Registration successful. Please wait for administrator approval."
    except Exception as e:
        return False, f"Registration failed: {str(e)}"
    finally:
        conn.close()

def get_all_users():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, username, email, role, status, ad_user FROM users ORDER BY status DESC, username ASC')
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_user_status(user_id, status):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET status = ? WHERE id = ?', (status, user_id))
    conn.commit()
    conn.close()
    return True

def update_user_role(user_id, role):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET role = ? WHERE id = ?', (role, user_id))
    conn.commit()
    conn.close()
    return True

def delete_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()
    return True

def update_ad_credentials(user_id, ad_user, ad_password):
    conn = get_db_connection()
    cursor = conn.cursor()
    enc_password = encrypt_val(ad_password) if ad_password else None
    cursor.execute(
        'UPDATE users SET ad_user = ?, ad_password_encrypted = ? WHERE id = ?',
        (ad_user.strip() if ad_user else None, enc_password, user_id)
    )
    conn.commit()
    conn.close()
    return True

def get_ad_credentials(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT ad_user, ad_password_encrypted FROM users WHERE id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        dec_password = decrypt_val(row['ad_password_encrypted']) if row['ad_password_encrypted'] else None
        return {
            "ad_user": row['ad_user'],
            "ad_password": dec_password
        }
    return None
