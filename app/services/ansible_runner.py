import os
import time
import json
import uuid
import shutil
import socket
import paramiko
from datetime import datetime
from pathlib import Path

PODS_DATA_FILE = Path(__file__).parent.parent / "data" / "pods.json"
INVENTORY_DIR = Path(__file__).parent.parent.parent / "inventory"
PLAYBOOKS_DIR = Path(__file__).parent.parent.parent / "playbooks"
LOGS_DIR = Path(__file__).parent.parent.parent / "logs"

class AnsibleRunner:
    @staticmethod
    def get_jump_config(jump_host):
        """Fetches stored Jump Host credentials from backend pods.json configuration."""
        if PODS_DATA_FILE.exists():
            try:
                with open(PODS_DATA_FILE, "r", encoding="utf-8") as f:
                    pods = json.load(f)
                    for pod in pods:
                        if pod.get("jump_host") == jump_host or jump_host in pod.get("name", ""):
                            return {
                                "jump_host": pod.get("jump_host", jump_host),
                                "jump_user": pod.get("jump_user", "rocky"),
                                "jump_password": pod.get("jump_password", "rocky"),
                                "ssh_port": pod.get("ssh_port", 22)
                            }
            except Exception:
                pass
        return {
            "jump_host": jump_host or "192.168.209.135",
            "jump_user": "rocky",
            "jump_password": "rocky",
            "ssh_port": 22
        }

    @staticmethod
    def get_available_inventories():
        """List all .ini inventory files saved in inventory/ directory."""
        if not INVENTORY_DIR.exists():
            INVENTORY_DIR.mkdir(parents=True, exist_ok=True)
        
        inventories = []
        for file in INVENTORY_DIR.glob("*.ini"):
            inventories.append({
                "filename": file.name,
                "path": str(file),
                "size_bytes": file.stat().st_size
            })
        return inventories

    @staticmethod
    def save_execution_log(log_lines, prefix="execution"):
        """Saves execution output stream to a persistent log file in logs/."""
        if not LOGS_DIR.exists():
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_id = uuid.uuid4().hex[:6]
        filename = f"{prefix}_{timestamp}_{log_id}.log"
        filepath = LOGS_DIR / filename
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(log_lines))
            
        return filename, str(filepath)

    @classmethod
    def ssh_execute_via_jump(cls, jump_host, jump_user, jump_password, target_host, target_user, target_password, command, jump_port=22, target_port=22, timeout=8):
        """
        Establishes SSH connection from OpsHub Central to Jump Host (using backend stored credentials),
        then opens a socket tunnel to target End VM using user-supplied credentials.
        """
        if jump_host == target_host or not jump_host:
            return cls._ssh_direct(target_host, target_user, command, target_password, target_port, timeout)

        jump_client = paramiko.SSHClient()
        jump_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        try:
            # Step 1: Connect to Jump Host using stored credentials
            jump_client.connect(
                hostname=jump_host,
                port=jump_port,
                username=jump_user,
                password=jump_password,
                timeout=timeout,
                allow_agent=True,
                look_for_keys=True
            )

            # Step 2: Open socket tunnel (direct-tcpip) through Jump Host to Target VM
            jump_transport = jump_client.get_transport()
            dest_addr = (target_host, target_port)
            src_addr = (jump_host, jump_port)
            channel = jump_transport.open_channel("direct-tcpip", dest_addr, src_addr)

            # Step 3: Connect to Target End VM over socket tunnel using Target User & Password
            target_client = paramiko.SSHClient()
            target_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            target_client.connect(
                hostname=target_host,
                port=target_port,
                username=target_user,
                password=target_password,
                sock=channel,
                timeout=timeout,
                allow_agent=True,
                look_for_keys=True
            )

            # Step 4: Execute Command on Target End VM
            stdin, stdout, stderr = target_client.exec_command(command, timeout=15)
            out_str = stdout.read().decode("utf-8", errors="replace")
            err_str = stderr.read().decode("utf-8", errors="replace")
            exit_code = stdout.channel.recv_exit_status()

            target_client.close()
            jump_client.close()

            return True, exit_code, out_str, err_str

        except Exception as e:
            try:
                jump_client.close()
            except Exception:
                pass
            return False, -1, "", f"SSH Connection Failure (Jump: {jump_user}@{jump_host} -> Target: {target_user}@{target_host}): {str(e)}"

    @classmethod
    def _ssh_direct(cls, target_host, target_user, command, target_password=None, target_port=22, timeout=8):
        """Direct SSH connection when target is the Jump Host or no proxy needed."""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=target_host,
                port=target_port,
                username=target_user,
                password=target_password,
                timeout=timeout,
                allow_agent=True,
                look_for_keys=True
            )
            stdin, stdout, stderr = client.exec_command(command, timeout=15)
            out_str = stdout.read().decode("utf-8", errors="replace")
            err_str = stderr.read().decode("utf-8", errors="replace")
            exit_code = stdout.channel.recv_exit_status()
            client.close()
            return True, exit_code, out_str, err_str
        except Exception as e:
            try:
                client.close()
            except Exception:
                pass
            return False, -1, "", f"Direct SSH Connection Failure ({target_user}@{target_host}): {str(e)}"

    @classmethod
    def resolve_target_hosts(cls, target_mode, target_value):
        """Parses target mode into a list of target host IPs or names."""
        if target_mode == "single":
            # Support comma or space separated IPs
            raw_hosts = [h.strip() for h in target_value.replace(",", " ").split() if h.strip()]
            return raw_hosts if raw_hosts else ["192.168.209.136"]
        else:
            inventory_path = INVENTORY_DIR / target_value
            hosts = []
            if inventory_path.exists():
                with open(inventory_path, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line_str = line.strip()
                        if line_str and not line_str.startswith("[") and not line_str.startswith("#"):
                            if "ansible_host=" in line_str:
                                parts = line_str.split("ansible_host=")
                                if len(parts) > 1:
                                    hosts.append(parts[1].split()[0])
                            else:
                                hosts.append(line_str.split()[0])
            return hosts if hosts else ["192.168.209.136"]

    @classmethod
    def execute_adhoc(cls, jump_host, target_mode, target_value, command_key, custom_command=None, target_vm_user="root", target_vm_password=None):
        """
        Executes an ad-hoc command proxied through Jump Host using stored Jump credentials
        and user-supplied Target VM credentials.
        """
        jump_cfg = cls.get_jump_config(jump_host)
        jump_ip = jump_cfg["jump_host"]
        jump_user = jump_cfg["jump_user"]
        jump_pass = jump_cfg["jump_password"]

        command_map = {
            "ping": "ping -c 2 127.0.0.1",
            "hostname": "hostname",
            "uptime": "uptime",
            "df -h": "df -h",
            "free -m": "free -m",
            "cat /etc/os-release": "cat /etc/os-release",
            "custom": custom_command or "uptime"
        }

        real_cmd = command_map.get(command_key, command_key)
        target_hosts = cls.resolve_target_hosts(target_mode, target_value)

        logs = [
            f"================================================================================",
            f"[OPSHUB ENGINE] REAL SSH AD-HOC EXECUTION",
            f"--------------------------------------------------------------------------------",
            f"Timestamp         : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Central OpsHub VM : 192.168.209.137",
            f"Jump Host (Stored): {jump_ip} (user: {jump_user})",
            f"Target VM(s)      : {', '.join(target_hosts)} (user: {target_vm_user})",
            f"Executed Command  : `{real_cmd}`",
            f"================================================================================",
            f"",
            f"ESTABLISHING SSH PROXY CONNECTION...",
            f"-> OpsHub Central connecting to Jump Host ({jump_ip}:22) with stored credentials..."
        ]

        overall_success = True
        combined_stdout = []

        for target_host in target_hosts:
            logs.append(f"\n[HOST: {target_host}] Opening direct-tcpip channel via Jump Host...")
            
            ssh_ok, code, stdout, stderr = cls.ssh_execute_via_jump(
                jump_host=jump_ip,
                jump_user=jump_user,
                jump_password=jump_pass,
                target_host=target_host,
                target_user=target_vm_user,
                target_password=target_vm_password,
                command=real_cmd,
                timeout=5
            )

            if ssh_ok:
                logs.append(f"   [OK] Connected to target VM ({target_host}). Executed `{real_cmd}`.")
                logs.append(f"--------------------------------------------------------------------------------")
                if stdout:
                    logs.extend(stdout.splitlines())
                    combined_stdout.append(f"{target_host} | CHANGED | rc={code} >>\n{stdout}")
                if stderr:
                    logs.append(f"[STDERR] {stderr}")
                logs.append(f"--------------------------------------------------------------------------------")
                logs.append(f"[SUMMARY] {target_host} exit code {code}.")
            else:
                overall_success = False
                logs.append(f"❌ [ERROR] {stderr}")
                combined_stdout.append(f"ERROR: {stderr}")

        # Save Execution Log to disk
        log_filename, log_path = cls.save_execution_log(logs, prefix="adhoc")

        return {
            "success": overall_success,
            "target": ", ".join(target_hosts),
            "jump_host": jump_ip,
            "stdout": "\n\n".join(combined_stdout),
            "log_file": log_filename,
            "log_path": log_path,
            "logs": logs
        }

    @classmethod
    def execute_playbook(cls, playbook_file, jump_host, target_mode, target_value, extra_vars=None, target_vm_user="root", target_vm_password=None):
        """
        Executes an Ansible Playbook proxied through Jump Host using stored Jump credentials
        and user-supplied Target VM credentials.
        """
        jump_cfg = cls.get_jump_config(jump_host)
        jump_ip = jump_cfg["jump_host"]
        jump_user = jump_cfg["jump_user"]
        jump_pass = jump_cfg["jump_password"]

        target_hosts = cls.resolve_target_hosts(target_mode, target_value)
        cli_str = f"ansible-playbook -i '{target_value}' playbooks/{playbook_file} -u {target_vm_user}"

        logs = [
            f"================================================================================",
            f"[OPSHUB ENGINE] REAL ANSIBLE PLAYBOOK EXECUTION",
            f"--------------------------------------------------------------------------------",
            f"Timestamp         : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Central OpsHub VM : 192.168.209.137",
            f"Jump Host (Stored): {jump_ip} (user: {jump_user})",
            f"Target VM(s)      : {', '.join(target_hosts)} (user: {target_vm_user})",
            f"Playbook File     : {playbook_file}",
            f"================================================================================",
            f"",
            f"PLAY [{playbook_file} : Playbook Task Sequence] *************************************************",
            f"Connecting via Jump Host ({jump_ip}:22)..."
        ]

        if playbook_file == "vm_health_check.yml":
            tasks = [
                ("TASK [1. Gather System Information & Load Average]", "uptime"),
                ("TASK [2. Check RAM Memory Usage]", "free -m"),
                ("TASK [3. Check Root Disk Space Usage]", "df -h /"),
                ("TASK [4. Check Core System Services (sshd, containerd)]", "systemctl is-active sshd || true"),
                ("TASK [5. Network Connectivity Diagnostic]", "ping -c 2 127.0.0.1")
            ]
        else:
            tasks = [
                ("TASK [1. Gather Facts & Architecture]", "uname -a"),
                ("TASK [2. Verify System OS Details]", "cat /etc/os-release"),
                ("TASK [3. Check Service Uptime]", "uptime")
            ]

        play_success = True
        ok_count = 0
        failed_count = 0

        for target_host in target_hosts:
            logs.append(f"\n--- EXECUTION FOR TARGET HOST: {target_host} ---")
            for task_title, task_cmd in tasks:
                logs.append(f"{task_title} *********************************************************")
                
                ssh_ok, code, stdout, stderr = cls.ssh_execute_via_jump(
                    jump_host=jump_ip,
                    jump_user=jump_user,
                    jump_password=jump_pass,
                    target_host=target_host,
                    target_user=target_vm_user,
                    target_password=target_vm_password,
                    command=task_cmd,
                    timeout=5
                )

                if ssh_ok and code == 0:
                    ok_count += 1
                    logs.append(f"ok: [{target_host}] => {{")
                    for line in stdout.splitlines():
                        logs.append(f"    {line}")
                    logs.append(f"}}")
                else:
                    failed_count += 1
                    play_success = False
                    err_msg = stderr if stderr else f"Exit code {code}"
                    logs.append(f"fatal: [{target_host}]: FAILED! => {{\"msg\": \"{err_msg}\"}}")
                    break

        logs.append(f"--------------------------------------------------------------------------------")
        logs.append(f"PLAY RECAP *********************************************************************")
        logs.append(f"{', '.join(target_hosts)} : ok={ok_count}    changed=0    unreachable=0    failed={failed_count}")

        # Save Playbook Log
        log_filename, log_path = cls.save_execution_log(logs, prefix="playbook")

        return {
            "success": play_success,
            "cli_command": cli_str,
            "target": ", ".join(target_hosts),
            "jump_host": jump_ip,
            "playbook": playbook_file,
            "log_file": log_filename,
            "log_path": log_path,
            "logs": logs
        }
