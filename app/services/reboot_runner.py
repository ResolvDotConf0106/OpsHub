import time
import uuid
import socket
import threading
import paramiko
import json
from datetime import datetime
from pathlib import Path

# Import audit helper lazily to avoid circular imports at module level
def _finish_exec_log(exec_id, status, duration):
    """Call log_execution_end safely from background thread."""
    try:
        from app.services.audit_service import log_execution_end
        log_execution_end(exec_id, status, duration)
    except Exception:
        pass

PODS_DATA_FILE = Path(__file__).parent.parent / "data" / "pods.json"
LOGS_DIR = Path(__file__).parent.parent.parent / "logs"
PRECHECKS_DIR = Path(__file__).parent.parent.parent / "logs"

# In-memory registry for running reboot jobs
reboot_jobs = {}
reboot_jobs_lock = threading.Lock()

# ─── Pre & Post Check Definitions ─────────────────────────────────────────────
PRECHECK_TASKS = [
    ("System Uptime",           "uptime"),
    ("OS Version",              "cat /etc/os-release | grep -E 'NAME|VERSION'"),
    ("Kernel Version",          "uname -r"),
    ("Disk Usage",              "df -h"),
    ("Memory Usage",            "free -m"),
    ("Mounted Filesystems",     "mount | grep -v tmpfs | head -30"),
    ("NTP Sync Status",         "timedatectl | head -10"),
    ("Failed Services",         "systemctl list-units --failed --no-pager --plain 2>/dev/null | head -20 || echo 'None'"),
    ("Running Services (key)",  "systemctl is-active sshd crond 2>/dev/null || true"),
]

POSTCHECK_TASKS = [
    ("Boot Timestamp",          "who -b"),
    ("System Uptime",           "uptime"),
    ("Kernel Version",          "uname -r"),
    ("Disk Usage",              "df -h"),
    ("Memory Usage",            "free -m"),
    ("Failed Services",         "systemctl list-units --failed --no-pager --plain 2>/dev/null | head -20 || echo 'None'"),
    ("SSH Service Status",      "systemctl is-active sshd"),
]


class RebootRunner:

    @staticmethod
    def get_jump_config(jump_host):
        """Fetch stored Jump Host credentials from pods.json."""
        if PODS_DATA_FILE.exists():
            try:
                with open(PODS_DATA_FILE, "r", encoding="utf-8") as f:
                    pods = json.load(f)
                    for pod in pods:
                        if pod.get("jump_host") == jump_host or jump_host in pod.get("name", ""):
                            return {
                                "jump_host": pod.get("jump_host", jump_host),
                                "jump_user": pod.get("jump_user", "root"),
                                "jump_password": pod.get("jump_password", ""),
                                "ssh_port": pod.get("ssh_port", 22)
                            }
            except Exception:
                pass
        return {
            "jump_host": jump_host,
            "jump_user": "root",
            "jump_password": "",
            "ssh_port": 22
        }

    @staticmethod
    def _save_log(lines, prefix="reboot"):
        """Save accumulated log lines to a file in logs/."""
        if not LOGS_DIR.exists():
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_id = uuid.uuid4().hex[:6]
        filename = f"{prefix}_{timestamp}_{log_id}.log"
        filepath = LOGS_DIR / filename
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(str(l) for l in lines))
        return filename, str(filepath)

    @staticmethod
    def _ssh_exec_via_jump(jump_ip, jump_user, jump_pass, jump_port,
                           target_host, target_user, target_pass, command, timeout=10):
        """
        Execute a command on target via Jump Host proxy. Returns (ok, exit_code, stdout, stderr).
        """
        jump_client = paramiko.SSHClient()
        jump_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            jump_client.connect(
                hostname=jump_ip, port=jump_port,
                username=jump_user, password=jump_pass,
                timeout=timeout, allow_agent=True, look_for_keys=True
            )
            jump_transport = jump_client.get_transport()
            channel = jump_transport.open_channel(
                "direct-tcpip", (target_host, 22), (jump_ip, jump_port)
            )
            target_client = paramiko.SSHClient()
            target_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            target_client.connect(
                hostname=target_host, port=22,
                username=target_user, password=target_pass,
                sock=channel, timeout=timeout,
                allow_agent=True, look_for_keys=True
            )
            if target_user != "root" and target_pass:
                stdin, stdout, stderr = target_client.exec_command("sudo -S -p '' sh", timeout=timeout)
                stdin.write(target_pass + "\n")
                stdin.write(command + "\n")
                stdin.flush()
                stdin.channel.shutdown_write()
            else:
                stdin, stdout, stderr = target_client.exec_command(command, timeout=timeout)

            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            code = stdout.channel.recv_exit_status()
            target_client.close()
            jump_client.close()
            return True, code, out, err
        except Exception as e:
            try:
                jump_client.close()
            except Exception:
                pass
            return False, -1, "", str(e)

    @staticmethod
    def _probe_ssh_port(host, port=22, timeout=2):
        """Returns True if TCP port is reachable (machine online)."""
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except Exception:
            return False

    # ─── Public API ───────────────────────────────────────────────────────────

    @classmethod
    def start_reboot_job(cls, jump_host, target_host, target_user, target_pass,
                         ticket_number, username, timeout_minutes=15):
        """
        Kick off a reboot job in a background daemon thread.
        Returns the job_id dict with initial state.
        """
        job_id = uuid.uuid4().hex[:10]
        start_time = datetime.now()

        with reboot_jobs_lock:
            reboot_jobs[job_id] = {
                "id": job_id,
                "ticket": ticket_number,
                "initiated_by": username,
                "target": target_host,
                "jump": jump_host,
                "status": "STARTING",
                "phase": 0,
                "events": [],
                "precheck_log": None,
                "full_log": None,
                "started_at": start_time.strftime("%Y-%m-%d %H:%M:%S"),
                "started_ts": start_time.timestamp(),
                "exec_id": None,       # set by caller after start
                "error": None,
            }

        t = threading.Thread(
            target=cls._run_reboot_pipeline,
            args=(job_id, jump_host, target_host, target_user, target_pass, timeout_minutes),
            daemon=True
        )
        t.start()
        return job_id

    @classmethod
    def set_exec_id(cls, job_id, exec_id):
        """Store the audit exec_id so the background thread can close it."""
        with reboot_jobs_lock:
            if job_id in reboot_jobs:
                reboot_jobs[job_id]["exec_id"] = exec_id

    @classmethod
    def _push_event(cls, job_id, message, level="INFO"):
        """Push a timestamped event string to the job's event list."""
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] [{level}] {message}"
        with reboot_jobs_lock:
            if job_id in reboot_jobs:
                reboot_jobs[job_id]["events"].append(entry)

    @classmethod
    def get_job_status(cls, job_id):
        """Returns a snapshot of job status dict (thread-safe read)."""
        with reboot_jobs_lock:
            job = reboot_jobs.get(job_id)
            if not job:
                return None
            return dict(job)   # shallow copy

    # ─── Pipeline ─────────────────────────────────────────────────────────────

    @classmethod
    def _run_reboot_pipeline(cls, job_id, jump_host, target_host, target_user,
                              target_pass, timeout_minutes):
        """
        Full reboot pipeline: pre-checks → reboot → ping watch → post-checks.
        Runs in a background daemon thread.
        """
        def set_status(status, phase):
            with reboot_jobs_lock:
                if job_id in reboot_jobs:
                    reboot_jobs[job_id]["status"] = status
                    reboot_jobs[job_id]["phase"] = phase

        def set_error(msg):
            with reboot_jobs_lock:
                if job_id in reboot_jobs:
                    reboot_jobs[job_id]["status"] = "ERROR"
                    reboot_jobs[job_id]["error"] = msg
                    exec_id_err = reboot_jobs[job_id].get("exec_id")
                    started_ts_err = reboot_jobs[job_id].get("started_ts", time.time())
            if exec_id_err:
                _finish_exec_log(exec_id_err, "Failed", round(time.time() - started_ts_err, 1))

        all_log_lines = []

        def log(msg, level="INFO"):
            cls._push_event(job_id, msg, level)
            all_log_lines.append(f"[{datetime.now().strftime('%H:%M:%S')}] [{level}] {msg}")

        jump_cfg = cls.get_jump_config(jump_host)
        jump_ip   = jump_cfg["jump_host"]
        jump_user = jump_cfg["jump_user"]
        jump_pass = jump_cfg["jump_password"]
        jump_port = jump_cfg["ssh_port"]

        # ── Header ─────────────────────────────────────────────────────────────
        all_log_lines += [
            "=" * 80,
            "[OPSHUB REBOOT ENGINE] CONTROLLED VM REBOOT",
            f"Ticket         : {reboot_jobs[job_id]['ticket']}",
            f"Jump Host      : {jump_ip}",
            f"Target VM      : {target_host}",
            f"User           : {target_user}",
            f"Initiated By   : {reboot_jobs[job_id]['initiated_by']}",
            f"Started At     : {reboot_jobs[job_id]['started_at']}",
            "=" * 80, ""
        ]

        # ─────────────────────────────────────────────────────────────────────
        # PHASE 1 — PRE-CHECKS
        # ─────────────────────────────────────────────────────────────────────
        set_status("PRECHECKS", 1)
        log("=== PHASE 1: PRE-CHECKS ===")
        all_log_lines.append("=== PRE-CHECKS ===")

        precheck_report_lines = [
            "=" * 80,
            "OPSHUB PRE-REBOOT CHECK REPORT",
            f"Target VM   : {target_host}",
            f"Jump Host   : {jump_ip}",
            f"Ticket      : {reboot_jobs[job_id]['ticket']}",
            f"Generated At: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 80, ""
        ]

        for check_name, cmd in PRECHECK_TASKS:
            log(f"Running pre-check: {check_name}...")
            ok, code, stdout, stderr = cls._ssh_exec_via_jump(
                jump_ip, jump_user, jump_pass, jump_port,
                target_host, target_user, target_pass, cmd, timeout=10
            )
            if ok:
                log(f"  ✅ {check_name}: OK", "SUCCESS")
                precheck_report_lines += [f"--- {check_name} ({cmd}) ---"]
                precheck_report_lines += [l.rstrip() for l in stdout.splitlines()] or ["(no output)"]
                precheck_report_lines.append("")
                all_log_lines += [f"  [{check_name}]", *[f"    {l}" for l in stdout.splitlines()]]
            else:
                log(f"  ⚠️  {check_name}: FAILED - {stderr.strip()[:120]}", "WARN")
                precheck_report_lines += [f"--- {check_name} ({cmd}) ---", f"ERROR: {stderr.strip()}", ""]
                all_log_lines.append(f"  [{check_name}] ERROR: {stderr.strip()[:120]}")

        # Save pre-check report
        precheck_filename, _ = cls._save_log(precheck_report_lines, prefix="precheck")
        with reboot_jobs_lock:
            if job_id in reboot_jobs:
                reboot_jobs[job_id]["precheck_log"] = precheck_filename
        log(f"Pre-check report saved: {precheck_filename}", "SUCCESS")

        # ─────────────────────────────────────────────────────────────────────
        # PHASE 2 — REBOOT COMMAND
        # ─────────────────────────────────────────────────────────────────────
        set_status("REBOOTING", 2)
        log("=== PHASE 2: ISSUING REBOOT COMMAND ===")
        all_log_lines += ["", "=== REBOOT ISSUED ==="]

        reboot_cmd = "nohup sh -c 'sleep 2 && shutdown -r now' >/dev/null 2>&1 &"
        ok, code, stdout, stderr = cls._ssh_exec_via_jump(
            jump_ip, jump_user, jump_pass, jump_port,
            target_host, target_user, target_pass, reboot_cmd, timeout=8
        )
        if ok:
            log("Reboot command issued successfully. System will restart in ~2 seconds.", "SUCCESS")
            all_log_lines.append("Reboot command issued. Waiting for system to go offline...")
        else:
            err_msg = f"Failed to issue reboot command: {stderr.strip()}"
            log(err_msg, "ERROR")
            set_error(err_msg)
            cls._save_log(all_log_lines, prefix="reboot")
            return

        time.sleep(3)  # Brief wait before starting to ping

        # ─────────────────────────────────────────────────────────────────────
        # PHASE 3 — LIVE PING WATCH
        # ─────────────────────────────────────────────────────────────────────
        set_status("PINGING", 3)
        log("=== PHASE 3: LIVE PING WATCH (via Jump Host TCP probe) ===")
        all_log_lines += ["", "=== PING WATCH ==="]

        timeout_seconds = timeout_minutes * 60
        probe_interval  = 5  # seconds between probes
        deadline        = time.time() + timeout_seconds
        went_offline    = False
        came_online     = False
        offline_at      = None
        downtime_secs   = 0

        # Track which probe to run via the jump host
        # (Direct TCP probe from OpsHub Central is fine for reachability)
        while time.time() < deadline:
            reachable = cls._probe_ssh_port(target_host, port=22, timeout=2)
            ts_str = datetime.now().strftime("%H:%M:%S")

            if not went_offline:
                if not reachable:
                    went_offline = True
                    offline_at = time.time()
                    log(f"🔴 {target_host}:22 → OFFLINE — System rebooting...", "WARN")
                    all_log_lines.append(f"[{ts_str}] {target_host}:22 → OFFLINE (system rebooting)")
                else:
                    log(f"🟡 {target_host}:22 → Still online, waiting for reboot...", "INFO")
                    all_log_lines.append(f"[{ts_str}] {target_host}:22 → Still ONLINE (waiting for reboot)")
            else:
                if reachable:
                    came_online = True
                    downtime_secs = int(time.time() - offline_at) if offline_at else 0
                    log(f"🟢 {target_host}:22 → ONLINE — System back up! (downtime: {downtime_secs}s)", "SUCCESS")
                    all_log_lines.append(f"[{ts_str}] {target_host}:22 → ONLINE — System back up! downtime={downtime_secs}s")
                    break
                else:
                    elapsed = int(time.time() - offline_at) if offline_at else 0
                    log(f"🔴 {target_host}:22 → OFFLINE — {elapsed}s elapsed, still rebooting...", "WARN")
                    all_log_lines.append(f"[{ts_str}] {target_host}:22 → OFFLINE ({elapsed}s elapsed)")

            time.sleep(probe_interval)

        if not came_online:
            err_msg = f"Timeout: {target_host} did not come back online within {timeout_minutes} minutes."
            log(err_msg, "ERROR")
            set_error(err_msg)
            full_filename, _ = cls._save_log(all_log_lines, prefix="reboot")
            with reboot_jobs_lock:
                if job_id in reboot_jobs:
                    reboot_jobs[job_id]["full_log"] = full_filename
            return

        # Wait a few extra seconds for SSH daemon to fully initialize
        log("System back up — waiting 8s for SSH daemon to stabilize...", "INFO")
        time.sleep(8)

        # ─────────────────────────────────────────────────────────────────────
        # PHASE 4 — POST-CHECKS
        # ─────────────────────────────────────────────────────────────────────
        set_status("POSTCHECKS", 4)
        log("=== PHASE 4: POST-CHECKS ===")
        all_log_lines += ["", "=== POST-CHECKS ==="]

        warnings = 0
        for check_name, cmd in POSTCHECK_TASKS:
            log(f"Running post-check: {check_name}...")
            ok, code, stdout, stderr = cls._ssh_exec_via_jump(
                jump_ip, jump_user, jump_pass, jump_port,
                target_host, target_user, target_pass, cmd, timeout=12
            )
            if ok:
                log(f"  ✅ {check_name}: OK", "SUCCESS")
                all_log_lines += [f"  [{check_name}]", *[f"    {l}" for l in stdout.splitlines()]]
            else:
                warnings += 1
                log(f"  ⚠️  {check_name}: WARNING - {stderr.strip()[:120]}", "WARN")
                all_log_lines.append(f"  [{check_name}] WARNING: {stderr.strip()[:120]}")

        # ── Final Summary ────────────────────────────────────────────────────
        total_seconds = int(time.time() - (offline_at - 3)) if offline_at else 0
        duration_str = f"{total_seconds // 60}m {total_seconds % 60}s"
        all_log_lines += [
            "", "=" * 80,
            f"=== REBOOT COMPLETE — DURATION: {duration_str} | WARNINGS: {warnings} ===",
            "=" * 80
        ]
        log(f"=== REBOOT COMPLETE — Total duration: {duration_str} | Warnings: {warnings} ===", "SUCCESS")

        full_filename, _ = cls._save_log(all_log_lines, prefix="reboot")
        exec_id = None
        started_ts = time.time()
        with reboot_jobs_lock:
            if job_id in reboot_jobs:
                reboot_jobs[job_id]["status"] = "DONE"
                reboot_jobs[job_id]["phase"] = 5
                reboot_jobs[job_id]["full_log"] = full_filename
                exec_id = reboot_jobs[job_id].get("exec_id")
                started_ts = reboot_jobs[job_id].get("started_ts", started_ts)

        # Close the audit execution record
        if exec_id:
            _finish_exec_log(exec_id, "Success", round(time.time() - started_ts, 1))
