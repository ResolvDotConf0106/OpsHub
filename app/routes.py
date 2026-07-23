from flask import Blueprint, render_template, request, jsonify, send_from_directory, session, redirect, url_for, flash
from pathlib import Path
from datetime import datetime
from app.services.pod_service import get_all_pods
from app.services.ansible_runner import AnsibleRunner, INVENTORY_DIR, LOGS_DIR, PLAYBOOKS_DIR
from app.services.static_ops_runner import StaticOpsRunner
from app.services.reboot_runner import RebootRunner, reboot_jobs, reboot_jobs_lock
from app.services.auth_service import (
    authenticate_user, register_user, get_all_users, update_user_status,
    update_user_role, delete_user, update_ad_credentials, get_ad_credentials,
    get_db_connection
)
from app.services.audit_service import (
    log_execution_start, log_execution_end, log_audit_event,
    get_all_executions, get_all_audit_events,
    delete_execution_logs, delete_audit_events
)

main = Blueprint("main", __name__)


@main.before_request
def require_login():
    allowed_endpoints = ['main.login', 'main.register', 'static']
    if 'user' not in session:
        if request.endpoint and request.endpoint not in allowed_endpoints:
            return redirect(url_for('main.login'))
    else:
        # Enforce RBAC route restrictions
        if request.endpoint and request.endpoint.startswith('main.admin_'):
            if session['user']['role'] not in ['Admin', 'Administrator']:
                flash("Access Denied: Administrative privileges required.")
                return redirect(url_for('main.dashboard'))


def _inject_ad_credentials(data, user_field='user', pass_field='password', use_ad=False):
    if use_ad:
        if 'user' in session:
            ad_creds = get_ad_credentials(session['user']['id'])
            if ad_creds and ad_creds['ad_user'] and ad_creds['ad_password']:
                return ad_creds['ad_user'], ad_creds['ad_password']
    return data.get(user_field), data.get(pass_field)



def check_jump_host_online(ip, port=22, timeout=1.0):
    import socket
    try:
        with socket.create_connection((ip, int(port)), timeout=timeout):
            return True
    except Exception:
        return False


@main.route("/")
def dashboard():
    pods = get_all_pods()
    
    online_count = 0
    for pod in pods:
        ip = pod.get("jump_host")
        port = pod.get("ssh_port", 22)
        is_online = check_jump_host_online(ip, port)
        pod["is_online"] = is_online
        if is_online:
            online_count += 1
            
    completed_jobs_count = 0
    recent_activities = []

    if LOGS_DIR.exists():
        log_files = sorted(LOGS_DIR.glob("*.log"), reverse=True)
        completed_jobs_count = len(log_files)
        
        for lf in log_files[:4]:
            mtime_str = datetime.fromtimestamp(lf.stat().st_mtime).strftime("%H:%M:%S")
            is_adhoc = "adhoc" in lf.name
            event_type = "Ad-Hoc Command" if is_adhoc else "Playbook Execution"
            recent_activities.append({
                "time": mtime_str,
                "type": "SUCCESS",
                "event": f"{event_type} recorded ({lf.name})"
            })

    if not recent_activities:
        recent_activities = [
            {"time": "Just now", "type": "INFO", "event": "Hyderabad POD online (Jump: 192.168.209.135, App: 192.168.209.136)"}
        ]
    
    total_pods = len(pods)
    health_percentage = 100
    if total_pods > 0:
        health_percentage = int((online_count / total_pods) * 100)

    metrics = {
        "total_pods": total_pods,
        "total_vms": total_pods * 2,
        "running_jobs": 0,
        "completed_jobs": completed_jobs_count,
        "cluster_health": f"{health_percentage}%"
    }

    return render_template(
        "dashboard.html",
        pods=pods,
        metrics=metrics,
        activities=recent_activities
    )


@main.route("/execute")
def execute():
    pods = get_all_pods()
    
    playbooks_list = []
    if PLAYBOOKS_DIR.exists():
        for yml in PLAYBOOKS_DIR.glob("*.yml"):
            title = yml.name.replace("_", " ").replace(".yml", "").title()
            playbooks_list.append({
                "id": yml.stem,
                "name": title,
                "file": yml.name,
                "category": "Automation"
            })

    if not playbooks_list:
        playbooks_list = [
            {"id": "vm_health_check", "name": "VM Health & Diagnostics Check", "file": "vm_health_check.yml", "category": "Diagnostics"}
        ]
    
    saved_inventories = AnsibleRunner.get_available_inventories()

    # Load Active Directory credentials info for the current user
    ad_creds = None
    if 'user' in session:
        ad_creds = get_ad_credentials(session['user']['id'])
    
    has_ad_creds = bool(ad_creds and ad_creds.get('ad_user') and ad_creds.get('ad_password'))
    ad_username = ad_creds.get('ad_user') if has_ad_creds else ""

    return render_template(
        "execute.html", 
        pods=pods, 
        playbooks=playbooks_list,
        inventories=saved_inventories,
        has_ad_creds=has_ad_creds,
        ad_username=ad_username
    )



@main.route("/api/execute_adhoc", methods=["POST"])
def execute_adhoc_api():
    data = request.get_json() or {}
    
    ticket_number = data.get("ticket_number")
    if not ticket_number or not ticket_number.strip():
        return jsonify({"success": False, "error": "Ticket Number is mandatory."}), 400
        
    jump_host = data.get("jump_host", "192.168.209.135")
    target_mode = data.get("target_mode", "single") # 'single' or 'inventory'
    target_value = data.get("target_value", "192.168.209.136")
    command_key = data.get("command_key", "uptime")
    custom_command = data.get("custom_command")
    use_ad = data.get("use_ad", False)
    target_vm_user, target_vm_password = _inject_ad_credentials(data, 'target_vm_user', 'target_vm_password', use_ad=use_ad)

    exec_id = log_execution_start(
        user_id=session['user']['id'] if 'user' in session else None,
        username=session['user']['username'] if 'user' in session else 'system',
        ticket_number=ticket_number,
        execution_type="Ad-Hoc Command",
        target_vm=target_value if target_mode == 'single' else 'Inventory',
        inventory_used="N/A" if target_mode == 'single' else target_value,
        playbook_or_command=custom_command if command_key == 'custom' else command_key,
        log_file=None
    )

    result = AnsibleRunner.execute_adhoc(
        jump_host=jump_host,
        target_mode=target_mode,
        target_value=target_value,
        command_key=command_key,
        custom_command=custom_command,
        target_vm_user=target_vm_user,
        target_vm_password=target_vm_password
    )

    success = result.get("success", False)
    status_str = "Success" if success else "Failed"
    duration = result.get("duration", 0.0)
    try:
        duration = float(duration)
    except:
        duration = 0.0
    
    log_filename = result.get("log_file")
    
    log_execution_end(exec_id, status_str, duration)
    if log_filename:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE execution_logs SET log_file = ? WHERE id = ?", (log_filename, exec_id))
        conn.commit()
        conn.close()

    return jsonify(result)


@main.route("/api/execute_playbook", methods=["POST"])
def execute_playbook_api():
    data = request.get_json() or {}
    
    ticket_number = data.get("ticket_number")
    if not ticket_number or not ticket_number.strip():
        return jsonify({"success": False, "error": "Ticket Number is mandatory."}), 400
        
    playbook_file = data.get("playbook_file", "vm_health_check.yml")
    jump_host = data.get("jump_host", "192.168.209.135")
    target_mode = data.get("target_mode", "single")
    target_value = data.get("target_value", "192.168.209.136")
    use_ad = data.get("use_ad", False)
    target_vm_user, target_vm_password = _inject_ad_credentials(data, 'target_vm_user', 'target_vm_password', use_ad=use_ad)
    extra_vars = data.get("extra_vars")

    exec_id = log_execution_start(
        user_id=session['user']['id'] if 'user' in session else None,
        username=session['user']['username'] if 'user' in session else 'system',
        ticket_number=ticket_number,
        execution_type="Playbook",
        target_vm=target_value if target_mode == 'single' else 'Inventory',
        inventory_used="N/A" if target_mode == 'single' else target_value,
        playbook_or_command=playbook_file,
        log_file=None
    )

    result = AnsibleRunner.execute_playbook(
        playbook_file=playbook_file,
        jump_host=jump_host,
        target_mode=target_mode,
        target_value=target_value,
        extra_vars=extra_vars,
        target_vm_user=target_vm_user,
        target_vm_password=target_vm_password
    )

    success = result.get("success", False)
    status_str = "Success" if success else "Failed"
    duration = result.get("duration", 0.0)
    try:
        duration = float(duration)
    except:
        duration = 0.0
    
    log_filename = result.get("log_file")
    
    log_execution_end(exec_id, status_str, duration)
    if log_filename:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE execution_logs SET log_file = ? WHERE id = ?", (log_filename, exec_id))
        conn.commit()
        conn.close()

    return jsonify(result)


@main.route("/api/upload_inventory", methods=["POST"])
def upload_inventory_api():
    if "file" in request.files:
        file = request.files["file"]
        if file.filename:
            filename = Path(file.filename).name
            if not filename.endswith(".ini"):
                filename += ".ini"
            save_path = INVENTORY_DIR / filename
            file.save(save_path)
            return jsonify({"success": True, "filename": filename, "message": "Inventory uploaded successfully."})
            
    data = request.get_json() or {}
    filename = data.get("filename", "custom_inventory.ini")
    if not filename.endswith(".ini"):
        filename += ".ini"
    content = data.get("content", "")
    
    save_path = INVENTORY_DIR / filename
    with open(save_path, "w", encoding="utf-8") as f:
        f.write(content)
        
    return jsonify({"success": True, "filename": filename, "message": "Inventory file saved successfully."})


@main.route("/api/download_log/<filename>")
def download_log_api(filename):
    """Allows downloading execution log files directly from logs/."""
    safe_name = Path(filename).name
    if not LOGS_DIR.exists() or not (LOGS_DIR / safe_name).exists():
        return jsonify({"error": "Log file not found."}), 404
        
    return send_from_directory(LOGS_DIR, safe_name, as_attachment=True)


@main.route("/api/delete_log/<filename>", methods=["POST"])
def delete_log_api(filename):
    """Allows administrators to permanently delete a log file."""
    if 'user' not in session or session['user'].get('role') not in ['Admin', 'Administrator']:
        return jsonify({"error": "Unauthorized Access"}), 403

    safe_name = Path(filename).name
    target_path = LOGS_DIR / safe_name
    if target_path.exists() and target_path.is_file():
        try:
            target_path.unlink()
            return jsonify({"success": True, "message": f"Log file {safe_name} deleted successfully."})
        except Exception as e:
            return jsonify({"error": f"Failed to delete: {str(e)}"}), 500

    return jsonify({"error": "File not found."}), 404


@main.route("/inventories")
def inventories():
    hosts = [
        {"name": "application-1", "ip": "192.168.209.136", "os": "Linux / Dev VM", "user": "root", "pod": "Hyderabad POD", "status": "ONLINE", "cpu": "Normal", "mem": "Nominal"},
        {"name": "hyder-jump-01", "ip": "192.168.209.135", "os": "Rocky Linux 9", "user": "rocky", "pod": "Hyderabad POD (Jump Host)", "status": "ONLINE", "cpu": "Normal", "mem": "Nominal"}
    ]

    saved_inventories = AnsibleRunner.get_available_inventories()

    return render_template("inventories.html", hosts=hosts, inventories=saved_inventories)


@main.route("/playbooks")
def playbooks():
    playbooks_data = []
    
    if PLAYBOOKS_DIR.exists():
        for yml in PLAYBOOKS_DIR.glob("*.yml"):
            title = yml.name.replace("_", " ").replace(".yml", "").title()
            playbooks_data.append({
                "title": title,
                "filename": yml.name,
                "description": f"Executable playbook file located at playbooks/{yml.name}",
                "tags": ["Diagnostics", "Ansible", "Automation"],
                "last_run": "Active",
                "author": "OpsTeam"
            })

    if not playbooks_data:
        playbooks_data = [
            {
                "title": "VM Health & Diagnostic Inspection",
                "filename": "vm_health_check.yml",
                "description": "Inspects CPU load, RAM usage, root disk space, network ping, and core systemd services across target VMs.",
                "tags": ["Diagnostics", "HealthCheck", "Monitoring"],
                "last_run": "Active",
                "author": "OpsTeam"
            }
        ]

    return render_template("playbooks.html", playbooks=playbooks_data)


@main.route("/jobs")
def jobs():
    executions = get_all_executions()
    job_history = []
    
    for ex in executions:
        # Calculate duration string
        dur = ex.get("duration")
        if dur is not None:
            secs = int(dur)
            mins = secs // 60
            rem_secs = secs % 60
            duration_str = f"{mins}m {rem_secs:02d}s"
        else:
            duration_str = "0m 00s"
            
        status_val = ex.get("status", "FAILED").upper() if ex.get("status") else "FAILED"
        # Standardize running text
        if status_val == "RUNNING":
            status_val = "RUNNING"
            
        job_history.append({
            "id": f"JOB-{ex['id']:03d}" if isinstance(ex.get('id'), int) else f"JOB-{ex.get('id')}",
            "playbook": ex.get("playbook_or_command") if ex.get("playbook_or_command") else ex.get("execution_type"),
            "pod": ex.get("target_vm") if ex.get("target_vm") else "Jump Host",
            "status": status_val,
            "duration": duration_str,
            "user": ex.get("username") if ex.get("username") else "system",
            "filename": ex.get("log_file") if ex.get("log_file") else "",
            "time": ex.get("start_time", "N/A")
        })

    return render_template("jobs.html", jobs=job_history)


@main.route("/logs")
def logs():
    saved_files = []
    if LOGS_DIR.exists():
        for f in sorted(LOGS_DIR.glob("*.log"), reverse=True):
            saved_files.append({
                "filename": f.name,
                "size_kb": round(f.stat().st_size / 1024, 2),
                "mtime": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            })

    return render_template("logs.html", saved_files=saved_files)


@main.route("/api/static_ops/disk_info", methods=["POST"])
def api_disk_info():
    data = request.get_json() or {}
    
    ticket_number = data.get("ticket_number")
    if not ticket_number or not ticket_number.strip():
        return jsonify({"success": False, "error": "Ticket Number is mandatory."}), 400
        
    jump_host = data.get("jump_host")
    target_host = data.get("target_host")
    use_ad = data.get("use_ad", False)
    user, password = _inject_ad_credentials(data, 'user', 'password', use_ad=use_ad)

    exec_id = log_execution_start(
        user_id=session['user']['id'] if 'user' in session else None,
        username=session['user']['username'] if 'user' in session else 'system',
        ticket_number=ticket_number,
        execution_type="Static Ops: Disk Info",
        target_vm=target_host,
        inventory_used="N/A",
        playbook_or_command="lsblk & df -h checks",
        log_file=None
    )

    success, result = StaticOpsRunner.get_disk_info(jump_host, target_host, user, password)
    
    log_file_name = f"disk_info_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    with open(log_dir / log_file_name, "w", encoding="utf-8") as f:
        f.write(result if isinstance(result, str) else str(result))

    status_str = "Success" if success else "Failed"
    log_execution_end(exec_id, status_str, 0.0)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE execution_logs SET log_file = ? WHERE id = ?", (log_file_name, exec_id))
    conn.commit()
    conn.close()

    if success:
        return jsonify({"success": True, "data": result})
    else:
        return jsonify({"success": False, "logs": result})


@main.route("/api/static_ops/create_filesystem", methods=["POST"])
def api_create_filesystem():
    data = request.get_json() or {}
    
    ticket_number = data.get("ticket_number")
    if not ticket_number or not ticket_number.strip():
        return jsonify({"success": False, "error": "Ticket Number is mandatory."}), 400
        
    jump_host = data.get("jump_host")
    target_host = data.get("target_host")
    use_ad = data.get("use_ad", False)
    user, password = _inject_ad_credentials(data, 'user', 'password', use_ad=use_ad)
    new_disk = data.get("new_disk")
    pv_name = data.get("pv_name")
    vg_name = data.get("vg_name")
    lv_name = data.get("lv_name")
    mount_point = data.get("mount_point")

    exec_id = log_execution_start(
        user_id=session['user']['id'] if 'user' in session else None,
        username=session['user']['username'] if 'user' in session else 'system',
        ticket_number=ticket_number,
        execution_type="Static Ops: LVM Provision",
        target_vm=target_host,
        inventory_used="N/A",
        playbook_or_command=f"Create LVM: {vg_name}/{lv_name} on {new_disk}",
        log_file=None
    )

    success, result = StaticOpsRunner.create_filesystem(
        jump_host, target_host, user, password, new_disk, pv_name, vg_name, lv_name, mount_point
    )

    log_file_name = f"lvm_create_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    with open(log_dir / log_file_name, "w", encoding="utf-8") as f:
        f.write(result if isinstance(result, str) else str(result))

    status_str = "Success" if success else "Failed"
    log_execution_end(exec_id, status_str, 0.0)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE execution_logs SET log_file = ? WHERE id = ?", (log_file_name, exec_id))
    conn.commit()
    conn.close()

    if success:
        return jsonify({"success": True, "data": result})
    else:
        return jsonify({"success": False, "logs": result})


@main.route("/api/static_ops/nfs_config", methods=["POST"])
def api_nfs_config():
    data = request.get_json() or {}
    
    ticket_number = data.get("ticket_number")
    if not ticket_number or not ticket_number.strip():
        return jsonify({"success": False, "error": "Ticket Number is mandatory."}), 400
        
    jump_host = data.get("jump_host")
    server_host = data.get("server_host")
    use_ad_server = data.get("use_ad_server", False)
    server_user, server_password = _inject_ad_credentials(data, 'server_user', 'server_password', use_ad=use_ad_server)
    client_host = data.get("client_host")
    use_ad_client = data.get("use_ad_client", False)
    client_user, client_password = _inject_ad_credentials(data, 'client_user', 'client_password', use_ad=use_ad_client)
    export_dir = data.get("export_dir")
    mount_dir = data.get("mount_dir")

    exec_id = log_execution_start(
        user_id=session['user']['id'] if 'user' in session else None,
        username=session['user']['username'] if 'user' in session else 'system',
        ticket_number=ticket_number,
        execution_type="Static Ops: NFS Link",
        target_vm=f"Srv:{server_host} / Cli:{client_host}",
        inventory_used="N/A",
        playbook_or_command=f"NFS mount: {export_dir} to {mount_dir}",
        log_file=None
    )

    success, result = StaticOpsRunner.configure_nfs(
        jump_host, server_host, server_user, server_password,
        client_host, client_user, client_password, export_dir, mount_dir
    )

    log_file_name = f"nfs_config_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    with open(log_dir / log_file_name, "w", encoding="utf-8") as f:
        f.write(result if isinstance(result, str) else str(result))

    status_str = "Success" if success else "Failed"
    log_execution_end(exec_id, status_str, 0.0)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE execution_logs SET log_file = ? WHERE id = ?", (log_file_name, exec_id))
    conn.commit()
    conn.close()

    if success:
        return jsonify({"success": True, "data": result})
    else:
        return jsonify({"success": False, "logs": result})


@main.route("/api/static_ops/telnet_check", methods=["POST"])
def api_telnet_check():
    data = request.get_json() or {}
    
    ticket_number = data.get("ticket_number")
    if not ticket_number or not ticket_number.strip():
        return jsonify({"success": False, "error": "Ticket Number is mandatory."}), 400
        
    jump_host = data.get("jump_host")
    target_host = data.get("target_host")
    use_ad = data.get("use_ad", False)
    user, password = _inject_ad_credentials(data, 'user', 'password', use_ad=use_ad)
    dest_host = data.get("dest_host")
    dest_port = data.get("dest_port")
    timeout = data.get("timeout", 3)

    exec_id = log_execution_start(
        user_id=session['user']['id'] if 'user' in session else None,
        username=session['user']['username'] if 'user' in session else 'system',
        ticket_number=ticket_number,
        execution_type="Static Ops: TCP Probe",
        target_vm=target_host,
        inventory_used="N/A",
        playbook_or_command=f"TCP check to {dest_host}:{dest_port} (timeout {timeout}s)",
        log_file=None
    )

    success, result = StaticOpsRunner.telnet_check_on_vm(
        jump_host, target_host, user, password, dest_host, dest_port, timeout
    )

    log_file_name = f"telnet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    with open(log_dir / log_file_name, "w", encoding="utf-8") as f:
        f.write(result if isinstance(result, str) else str(result))

    status_str = "Success" if success else "Failed"
    log_execution_end(exec_id, status_str, 0.0)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE execution_logs SET log_file = ? WHERE id = ?", (log_file_name, exec_id))
    conn.commit()
    conn.close()

    if success:
        return jsonify({"success": True, "data": result})
    else:
        return jsonify({"success": False, "result": result})


@main.route("/login", methods=["GET", "POST"])
def login():
    if 'user' in session:
        return redirect(url_for('main.dashboard'))
        
    error = None
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        user = authenticate_user(username, password)
        if isinstance(user, dict) and "error" in user:
            error = user["error"]
            log_audit_event(None, username, "Login Attempt Blocked", error)
        elif user:
            session['user'] = user
            log_audit_event(user['id'], user['username'], "Login", "User logged in successfully.")
            return redirect(url_for('main.dashboard'))
        else:
            error = "Invalid username or password"
            log_audit_event(None, username, "Login Failure", "Invalid credentials entered.")
            
    return render_template("login.html", error=error)


@main.route("/logout")
def logout():
    if 'user' in session:
        log_audit_event(session['user']['id'], session['user']['username'], "Logout", "User logged out.")
    session.pop('user', None)
    return redirect(url_for('main.login'))


@main.route("/register", methods=["GET", "POST"])
def register():
    if 'user' in session:
        return redirect(url_for('main.dashboard'))
        
    error = None
    success = None
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")
        
        ok, msg = register_user(username, email, password)
        if ok:
            success = "Your registration request has been sent to the administrator. Please wait for approval before accessing the application."
            log_audit_event(None, username, "Register", f"Account created with email: {email} (Status: Pending)")
        else:
            error = msg
            log_audit_event(None, username, "Register Failure", f"Failed registration: {msg}")
            
    return render_template("register.html", error=error, success=success)


@main.route("/profile", methods=["GET", "POST"])
def profile():
    if 'user' in session and session['user']['role'] in ['Admin', 'Administrator']:
        return redirect(url_for('main.dashboard'))
        
    user_id = session['user']['id']
    success = None
    error = None
    
    if request.method == "POST":
        ad_user = request.form.get("ad_user")
        ad_password = request.form.get("ad_password")
        
        if update_ad_credentials(user_id, ad_user, ad_password):
            success = "Active Directory credentials saved successfully."
        else:
            error = "Failed to save credentials."
            
    ad_creds = get_ad_credentials(user_id) or {"ad_user": "", "ad_password": ""}
    return render_template("profile.html", ad_creds=ad_creds, success=success, error=error)


@main.route("/admin/users")
def admin_users():
    users_list = get_all_users()
    return render_template("admin_users.html", users=users_list)


@main.route("/api/admin/users/<int:user_id>/action", methods=["POST"])
def admin_user_action(user_id):
    data = request.get_json() or {}
    action = data.get("action")
    actor = session['user']['username'] if 'user' in session else 'system'
    
    if action == "approve":
        update_user_status(user_id, "Approved")
        log_audit_event(user_id, actor, "Approve Account", f"Approved user request.")
        return jsonify({"success": True, "message": "User request approved."})
    elif action == "reject":
        update_user_status(user_id, "Rejected")
        log_audit_event(user_id, actor, "Reject Account", f"Rejected user request.")
        return jsonify({"success": True, "message": "User request rejected."})
    elif action == "disable":
        update_user_status(user_id, "Disabled")
        log_audit_event(user_id, actor, "Disable Account", f"Disabled user account.")
        return jsonify({"success": True, "message": "User account disabled."})
    elif action == "delete":
        log_audit_event(user_id, actor, "Delete Account", f"Permanently deleted user account.")
        delete_user(user_id)
        return jsonify({"success": True, "message": "User account deleted."})
        
    return jsonify({"success": False, "message": "Invalid action specified."})


@main.route("/admin/audit")
def admin_audit():
    executions_list = get_all_executions()
    events_list = get_all_audit_events()
    return render_template("admin_audit.html", executions=executions_list, events=events_list)


@main.route("/api/audit/log/<filename>")
def api_audit_log_content(filename):
    if 'user' not in session or session['user']['role'] not in ['Admin', 'Administrator']:
        return jsonify({"success": False, "error": "Access Denied."}), 403
        
    safe_name = Path(filename).name
    log_path = LOGS_DIR / safe_name
    if not log_path.exists():
        return jsonify({"success": False, "error": "Log file not found."}), 404
        
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return jsonify({"success": True, "content": content})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@main.route("/api/playbooks/<filename>")
def api_playbook_content(filename):
    if 'user' not in session:
        return jsonify({"success": False, "error": "Authentication required."}), 401
        
    safe_name = Path(filename).name
    playbook_path = PLAYBOOKS_DIR / safe_name
    if not playbook_path.exists() or not playbook_path.is_file():
        return jsonify({"success": False, "error": "Playbook file not found."}), 404
        
    try:
        with open(playbook_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return jsonify({"success": True, "content": content})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@main.route("/api/admin/delete_execution_logs", methods=["POST"])
def admin_delete_execution_logs():
    if 'user' not in session or session['user']['role'] not in ['Admin', 'Administrator']:
        return jsonify({"success": False, "error": "Access Denied."}), 403
    data = request.get_json() or {}
    log_ids = data.get("ids", [])
    if not log_ids:
        return jsonify({"success": False, "error": "No log IDs specified."}), 400
    try:
        delete_execution_logs(log_ids)
        log_audit_event(session['user']['id'], session['user']['username'], "Clear Execution Logs", f"Deleted {len(log_ids)} execution logs.")
        return jsonify({"success": True, "message": f"Successfully deleted {len(log_ids)} execution logs."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@main.route("/api/admin/delete_audit_events", methods=["POST"])
def admin_delete_audit_events():
    if 'user' not in session or session['user']['role'] not in ['Admin', 'Administrator']:
        return jsonify({"success": False, "error": "Access Denied."}), 403
    data = request.get_json() or {}
    event_ids = data.get("ids", [])
    if not event_ids:
        return jsonify({"success": False, "error": "No event IDs specified."}), 400
    try:
        delete_audit_events(event_ids)
        log_audit_event(session['user']['id'], session['user']['username'], "Clear Audit Events", f"Deleted {len(event_ids)} security audit events.")
        return jsonify({"success": True, "message": f"Successfully deleted {len(event_ids)} audit events."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# REBOOT TASK ENGINE
# ─────────────────────────────────────────────────────────────────────────────

@main.route("/api/reboot/start", methods=["POST"])
def reboot_start():
    """Kick off a background reboot job. Returns job_id and precheck status immediately."""
    data = request.get_json() or {}

    ticket_number = data.get("ticket_number", "").strip()
    if not ticket_number:
        return jsonify({"success": False, "error": "Ticket Number is mandatory."}), 400

    jump_host     = data.get("jump_host", "")
    target_ip     = data.get("target_ip", "")
    target_user   = data.get("target_user", "root")
    target_pass   = data.get("target_password", "")
    use_ad        = data.get("use_ad", False)
    timeout_min   = int(data.get("timeout_minutes", 15))

    # Optionally inject AD credentials
    if use_ad and 'user' in session:
        from app.services.auth_service import get_ad_credentials
        ad = get_ad_credentials(session['user']['id'])
        if ad and ad.get('ad_user') and ad.get('ad_password'):
            target_user = ad['ad_user']
            target_pass = ad['ad_password']

    if not jump_host or not target_ip:
        return jsonify({"success": False, "error": "Jump Host and Target IP are required."}), 400

    username = session['user']['username'] if 'user' in session else 'system'

    # Log execution start in audit DB
    exec_id = log_execution_start(
        user_id=session['user']['id'] if 'user' in session else None,
        username=username,
        ticket_number=ticket_number,
        execution_type="Controlled Reboot",
        target_vm=target_ip,
        inventory_used="N/A",
        playbook_or_command="reboot",
        log_file=None
    )

    job_id = RebootRunner.start_reboot_job(
        jump_host=jump_host,
        target_host=target_ip,
        target_user=target_user,
        target_pass=target_pass,
        ticket_number=ticket_number,
        username=username,
        timeout_minutes=timeout_min
    )

    # Wire exec_id into the job so the background thread closes the audit record
    RebootRunner.set_exec_id(job_id, exec_id)

    return jsonify({"success": True, "job_id": job_id, "exec_id": exec_id})


@main.route("/api/reboot/<job_id>/status", methods=["GET"])
def reboot_status(job_id):
    """Poll endpoint: returns current job state + new events since last_index."""
    import threading
    job = RebootRunner.get_job_status(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404

    # Client sends ?since=N to receive only events after index N
    since = int(request.args.get("since", 0))
    all_events = job.get("events", [])
    new_events  = all_events[since:]

    return jsonify({
        "job_id":        job_id,
        "status":        job["status"],
        "phase":         job["phase"],
        "target":        job["target"],
        "events":        new_events,
        "total_events":  len(all_events),
        "precheck_log":  job.get("precheck_log"),
        "full_log":      job.get("full_log"),
        "error":         job.get("error"),
    })


@main.route("/api/reboot/<job_id>/terminate", methods=["POST"])
def terminate_reboot(job_id):
    import time
    with reboot_jobs_lock:
        if job_id in reboot_jobs:
            reboot_jobs[job_id]["status"] = "ERROR"
            reboot_jobs[job_id]["error"] = "Terminated by user midway."
            exec_id = reboot_jobs[job_id].get("exec_id")
            started_ts = reboot_jobs[job_id].get("started_ts", time.time())
    
    if exec_id:
        try:
            from app.services.audit_service import log_execution_end
            log_execution_end(exec_id, "Failed", round(time.time() - started_ts, 1))
        except Exception:
            pass
            
    return jsonify({"success": True})


@main.route("/api/dashboard/running_jobs", methods=["GET"])
def get_running_jobs_metric():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM execution_logs WHERE status = 'Running'")
    running_count = cursor.fetchone()[0]
    
    # Also fetch recent activities dynamically!
    recent_activities = []
    if LOGS_DIR.exists():
        log_files = sorted(LOGS_DIR.glob("*.log"), key=lambda x: x.stat().st_mtime, reverse=True)
        for lf in log_files[:4]:
            mtime_str = datetime.fromtimestamp(lf.stat().st_mtime).strftime("%H:%M:%S")
            is_adhoc = "adhoc" in lf.name
            event_type = "Ad-Hoc Command" if is_adhoc else "Playbook Execution"
            recent_activities.append({
                "time": mtime_str,
                "type": "SUCCESS",
                "event": f"{event_type} recorded ({lf.name})"
            })
    conn.close()
    
    return jsonify({
        "running_jobs": running_count,
        "recent_activities": recent_activities
    })
