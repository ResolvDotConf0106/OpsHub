import sqlite3
from datetime import datetime
from app.services.auth_service import get_db_connection

def log_execution_start(user_id, username, ticket_number, execution_type, target_vm, inventory_used, playbook_or_command, log_file=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = "Running"
    
    cursor.execute('''
        INSERT INTO execution_logs (
            user_id, username, ticket_number, execution_type, target_vm, 
            inventory_used, playbook_or_command, status, start_time, log_file
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        user_id, username, ticket_number.strip(), execution_type, 
        target_vm, inventory_used, playbook_or_command, status, start_time, log_file
    ))
    
    execution_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return execution_id

def log_execution_end(execution_id, status, duration=0.0):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute('''
        UPDATE execution_logs 
        SET status = ?, end_time = ?, duration = ?
        WHERE id = ?
    ''', (status, end_time, duration, execution_id))
    
    conn.commit()
    conn.close()
    return True

def log_audit_event(user_id, actor_username, action_type, details=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute('''
        INSERT INTO audit_events (
            user_id, actor_username, action_type, timestamp, details
        ) VALUES (?, ?, ?, ?, ?)
    ''', (user_id, actor_username, action_type, timestamp, details))
    
    conn.commit()
    conn.close()
    return True

def get_all_executions():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, user_id, username, ticket_number, execution_type, target_vm, 
               inventory_used, playbook_or_command, status, start_time, end_time, 
               duration, log_file
        FROM execution_logs 
        ORDER BY start_time DESC
    ''')
    
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_all_audit_events():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, user_id, actor_username, action_type, timestamp, details 
        FROM audit_events 
        ORDER BY timestamp DESC
    ''')
    
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_execution_logs(log_ids):
    if not log_ids:
        return False
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholders = ",".join(["?"] * len(log_ids))
    cursor.execute(f"DELETE FROM execution_logs WHERE id IN ({placeholders})", [int(x) for x in log_ids])
    conn.commit()
    conn.close()
    return True

def delete_audit_events(event_ids):
    if not event_ids:
        return False
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholders = ",".join(["?"] * len(event_ids))
    cursor.execute(f"DELETE FROM audit_events WHERE id IN ({placeholders})", [int(x) for x in event_ids])
    conn.commit()
    conn.close()
    return True
