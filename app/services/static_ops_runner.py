import time
import socket
from datetime import datetime
from app.services.ansible_runner import AnsibleRunner

class StaticOpsRunner:
    @classmethod
    def get_disk_info(cls, jump_host, target_host, target_user, target_password):
        jump_cfg = AnsibleRunner.get_jump_config(jump_host)
        jump_ip = jump_cfg["jump_host"]
        jump_user = jump_cfg["jump_user"]
        jump_pass = jump_cfg["jump_password"]

        logs = [
            "================================================================================",
            "[STATIC OPS ENGINE] DISK INFORMATION GATHERING",
            "--------------------------------------------------------------------------------",
            f"Timestamp         : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Target VM         : {target_host} (user: {target_user})",
            "================================================================================",
            "CONNECTING VIA JUMP HOST...",
        ]

        # 1. lsblk
        logs.append("\nTASK [1. Display Block Devices (lsblk)] ****************************************")
        ok1, code1, out1, err1 = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip,
            jump_user=jump_user,
            jump_password=jump_pass,
            target_host=target_host,
            target_user=target_user,
            target_password=target_password,
            command="lsblk"
        )
        if ok1:
            logs.append(f"Exit Code: {code1}")
            logs.extend(out1.splitlines())
            if err1:
                logs.append(f"[STDERR] {err1}")
        else:
            logs.append(f"❌ [ERROR] SSH execution failed: {err1}")
            return False, logs

        # 2. df -h
        logs.append("\nTASK [2. Display Disk Usage (df -h)] *******************************************")
        ok2, code2, out2, err2 = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip,
            jump_user=jump_user,
            jump_password=jump_pass,
            target_host=target_host,
            target_user=target_user,
            target_password=target_password,
            command="df -h"
        )
        if ok2:
            logs.append(f"Exit Code: {code2}")
            logs.extend(out2.splitlines())
            if err2:
                logs.append(f"[STDERR] {err2}")
        else:
            logs.append(f"❌ [ERROR] SSH execution failed: {err2}")
            return False, logs

        log_file, log_path = AnsibleRunner.save_execution_log(logs, prefix="disk_info")
        return True, {
            "log_file": log_file,
            "stdout": out1 + "\n\n" + out2,
            "logs": logs
        }

    @classmethod
    def create_filesystem(cls, jump_host, target_host, target_user, target_password, new_disk, pv_name, vg_name, lv_name, mount_point):
        jump_cfg = AnsibleRunner.get_jump_config(jump_host)
        jump_ip = jump_cfg["jump_host"]
        jump_user = jump_cfg["jump_user"]
        jump_pass = jump_cfg["jump_password"]

        logs = [
            "================================================================================",
            "[STATIC OPS ENGINE] LVM FILE SYSTEM CREATION",
            "--------------------------------------------------------------------------------",
            f"Timestamp         : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Target VM         : {target_host} (user: {target_user})",
            f"Parameters: ",
            f"  New Disk        : {new_disk}",
            f"  PV Name         : {pv_name}",
            f"  VG Name         : {vg_name}",
            f"  LV Name         : {lv_name}",
            f"  Mount Point     : {mount_point}",
            "================================================================================",
            "CONNECTING VIA JUMP HOST...",
        ]

        # Step 1: Create PV
        logs.append("\nTASK [1. Create Physical Volume (PV)] ******************************************")
        cmd = f"pvcreate -y -f {pv_name}"
        logs.append(f"Executing: {cmd}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=target_host, target_user=target_user, target_password=target_password,
            command=cmd
        )
        if not ok or code != 0:
            logs.append(f"❌ [FAILED] pvcreate failed. Code: {code}, Error: {err or out}")
            AnsibleRunner.save_execution_log(logs, prefix="fs_create_fail")
            return False, logs
        logs.append(f"Success: {out.strip()}")

        # Step 2: Create VG
        logs.append("\nTASK [2. Create Volume Group (VG)] *********************************************")
        cmd = f"vgcreate -y {vg_name} {pv_name}"
        logs.append(f"Executing: {cmd}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=target_host, target_user=target_user, target_password=target_password,
            command=cmd
        )
        if not ok or code != 0:
            logs.append(f"❌ [FAILED] vgcreate failed. Code: {code}, Error: {err or out}")
            AnsibleRunner.save_execution_log(logs, prefix="fs_create_fail")
            return False, logs
        logs.append(f"Success: {out.strip()}")

        # Step 3: Create LV
        logs.append("\nTASK [3. Create Logical Volume (LV)] *******************************************")
        cmd = f"lvcreate -y -l 100%FREE -n {lv_name} {vg_name}"
        logs.append(f"Executing: {cmd}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=target_host, target_user=target_user, target_password=target_password,
            command=cmd
        )
        if not ok or code != 0:
            logs.append(f"❌ [FAILED] lvcreate failed. Code: {code}, Error: {err or out}")
            AnsibleRunner.save_execution_log(logs, prefix="fs_create_fail")
            return False, logs
        logs.append(f"Success: {out.strip()}")

        # Step 4: Format as XFS
        logs.append("\nTASK [4. Format Logical Volume as XFS] *****************************************")
        cmd = f"mkfs.xfs -f /dev/{vg_name}/{lv_name}"
        logs.append(f"Executing: {cmd}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=target_host, target_user=target_user, target_password=target_password,
            command=cmd
        )
        if not ok or code != 0:
            logs.append(f"❌ [FAILED] mkfs.xfs failed. Code: {code}, Error: {err or out}")
            AnsibleRunner.save_execution_log(logs, prefix="fs_create_fail")
            return False, logs
        logs.append(f"Success: {out.strip()}")

        # Step 5: Backup /etc/fstab
        logs.append("\nTASK [5. Backup /etc/fstab] ****************************************************")
        cmd = "cp /etc/fstab /etc/fstab.bak"
        logs.append(f"Executing: {cmd}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=target_host, target_user=target_user, target_password=target_password,
            command=cmd
        )
        if not ok or code != 0:
            logs.append(f"❌ [FAILED] fstab backup failed. Code: {code}, Error: {err or out}")
            AnsibleRunner.save_execution_log(logs, prefix="fs_create_fail")
            return False, logs
        logs.append("Success. Backup file /etc/fstab.bak created.")

        # Step 6: Create mount directory
        logs.append("\nTASK [6. Ensure Mount Directory Exists] ****************************************")
        cmd = f"mkdir -p {mount_point}"
        logs.append(f"Executing: {cmd}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=target_host, target_user=target_user, target_password=target_password,
            command=cmd
        )
        if not ok or code != 0:
            logs.append(f"❌ [FAILED] mkdir failed. Code: {code}, Error: {err or out}")
            AnsibleRunner.save_execution_log(logs, prefix="fs_create_fail")
            return False, logs
        logs.append(f"Success: Mount point {mount_point} ready.")

        # Step 7: Update /etc/fstab
        logs.append("\nTASK [7. Update /etc/fstab] ****************************************************")
        fstab_entry = f"/dev/{vg_name}/{lv_name} {mount_point} xfs defaults 0 0"
        cmd = f"grep -qF '{mount_point}' /etc/fstab || echo '{fstab_entry}' >> /etc/fstab"
        logs.append(f"Executing: {cmd}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=target_host, target_user=target_user, target_password=target_password,
            command=cmd
        )
        if not ok or code != 0:
            logs.append(f"❌ [FAILED] Updating fstab failed. Code: {code}, Error: {err or out}")
            AnsibleRunner.save_execution_log(logs, prefix="fs_create_fail")
            return False, logs
        logs.append(f"Success. Appended: {fstab_entry}")

        # Step 8: Mount the filesystem
        logs.append("\nTASK [8. Mount Filesystem] *****************************************************")
        cmd = "mount -a"
        logs.append(f"Executing: {cmd}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=target_host, target_user=target_user, target_password=target_password,
            command=cmd
        )
        if not ok or code != 0:
            logs.append(f"❌ [FAILED] mount failed. Code: {code}, Error: {err or out}")
            AnsibleRunner.save_execution_log(logs, prefix="fs_create_fail")
            return False, logs
        logs.append("Success: Filesystem mounted.")

        # Step 9: Verify Mount
        logs.append("\nTASK [9. Verify Mounted Filesystem Status] *************************************")
        cmd = f"df -h {mount_point} && mount | grep {mount_point}"
        logs.append(f"Executing: {cmd}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=target_host, target_user=target_user, target_password=target_password,
            command=cmd
        )
        if ok:
            logs.extend(out.splitlines())
            if err:
                logs.append(f"[STDERR] {err}")
        else:
            logs.append(f"❌ [ERROR] Verification failed: {err}")
            AnsibleRunner.save_execution_log(logs, prefix="fs_create_fail")
            return False, logs

        log_file, log_path = AnsibleRunner.save_execution_log(logs, prefix="fs_create")
        return True, {
            "log_file": log_file,
            "stdout": out,
            "logs": logs
        }

    @classmethod
    def configure_nfs(cls, jump_host, server_host, server_user, server_pass, client_host, client_user, client_pass, export_dir, mount_dir):
        jump_cfg = AnsibleRunner.get_jump_config(jump_host)
        jump_ip = jump_cfg["jump_host"]
        jump_user = jump_cfg["jump_user"]
        jump_pass = jump_cfg["jump_password"]

        logs = [
            "================================================================================",
            "[STATIC OPS ENGINE] NFS CONFIGURATION AUTOMATION",
            "--------------------------------------------------------------------------------",
            f"Timestamp         : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"NFS Server Host   : {server_host} (user: {server_user})",
            f"NFS Client Host   : {client_host} (user: {client_user})",
            f"Parameters: ",
            f"  Export Directory: {export_dir}",
            f"  Mount Directory : {mount_dir}",
            "================================================================================",
            "CONNECTING VIA JUMP HOST...",
        ]

        # ----------------SERVER CONFIGURATION----------------
        logs.append("\n=================== NFS SERVER CONFIGURATION ===================")
        
        # Step 1: Install nfs-utils on Server
        logs.append("\nTASK [1. Install nfs-utils on Server] ******************************************")
        cmd = "dnf install -y nfs-utils"
        logs.append(f"Executing: {cmd}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=server_host, target_user=server_user, target_password=server_pass,
            command=cmd
        )
        if not ok or code != 0:
            logs.append(f"❌ [FAILED] Server package installation failed. Code: {code}, Error: {err or out}")
            AnsibleRunner.save_execution_log(logs, prefix="nfs_config_fail")
            return False, logs
        logs.append(f"Success: {out.strip()}")

        # Step 2: Start/Enable NFS Server service
        logs.append("\nTASK [2. Enable and Start NFS Server Service] **********************************")
        cmd = "systemctl enable --now nfs-server"
        logs.append(f"Executing: {cmd}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=server_host, target_user=server_user, target_password=server_pass,
            command=cmd
        )
        if not ok or code != 0:
            logs.append(f"❌ [FAILED] Server systemctl failed. Code: {code}, Error: {err or out}")
            AnsibleRunner.save_execution_log(logs, prefix="nfs_config_fail")
            return False, logs
        logs.append("Success: NFS service running.")

        # Step 3: Create Export Directory
        logs.append("\nTASK [3. Create and set Export Directory permissions] *************************")
        cmd = f"mkdir -p {export_dir} && chmod 777 {export_dir}"
        logs.append(f"Executing: {cmd}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=server_host, target_user=server_user, target_password=server_pass,
            command=cmd
        )
        if not ok or code != 0:
            logs.append(f"❌ [FAILED] Server directory creation failed. Code: {code}, Error: {err or out}")
            AnsibleRunner.save_execution_log(logs, prefix="nfs_config_fail")
            return False, logs
        logs.append(f"Success: Export directory {export_dir} created.")

        # Step 4: Configure Exports
        logs.append("\nTASK [4. Update /etc/exports] **************************************************")
        export_entry = f"{export_dir} *(rw,sync,no_root_squash)"
        cmd = f"grep -qF '{export_dir}' /etc/exports || echo '{export_entry}' >> /etc/exports"
        logs.append(f"Executing: {cmd}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=server_host, target_user=server_user, target_password=server_pass,
            command=cmd
        )
        if not ok or code != 0:
            logs.append(f"❌ [FAILED] Server exports update failed. Code: {code}, Error: {err or out}")
            AnsibleRunner.save_execution_log(logs, prefix="nfs_config_fail")
            return False, logs
        logs.append(f"Success: Exports file updated with {export_entry}")

        # Step 5: Reload Export Table
        logs.append("\nTASK [5. Reload exportfs] ******************************************************")
        cmd = "exportfs -rav"
        logs.append(f"Executing: {cmd}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=server_host, target_user=server_user, target_password=server_pass,
            command=cmd
        )
        if not ok or code != 0:
            logs.append(f"❌ [FAILED] exportfs reload failed. Code: {code}, Error: {err or out}")
            AnsibleRunner.save_execution_log(logs, prefix="nfs_config_fail")
            return False, logs
        logs.append(f"Success: {out.strip()}")

        # Step 6: Server Firewall opening
        logs.append("\nTASK [6. Open firewall services for NFS] ***************************************")
        cmd = "firewall-cmd --add-service=nfs --permanent && firewall-cmd --reload"
        logs.append(f"Executing: {cmd}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=server_host, target_user=server_user, target_password=server_pass,
            command=cmd
        )
        if not ok or code != 0:
            logs.append(f"[WARNING] Firewall not updated (service may be inactive or absent): {err or out}")
        else:
            logs.append("Success: Firewall ports opened.")

        # Step 7: Verify with showmount
        logs.append("\nTASK [7. Verify Exports locally (showmount -e)] ********************************")
        cmd = "showmount -e localhost"
        logs.append(f"Executing: {cmd}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=server_host, target_user=server_user, target_password=server_pass,
            command=cmd
        )
        if ok:
            logs.extend(out.splitlines())
        else:
            logs.append(f"[WARNING] Local showmount check failed: {err}")


        # ----------------CLIENT CONFIGURATION----------------
        logs.append("\n=================== NFS CLIENT CONFIGURATION ===================")

        # Step 8: Install nfs-utils on Client
        logs.append("\nTASK [8. Install nfs-utils on Client] ******************************************")
        cmd = "dnf install -y nfs-utils"
        logs.append(f"Executing: {cmd}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=client_host, target_user=client_user, target_password=client_pass,
            command=cmd
        )
        if not ok or code != 0:
            logs.append(f"❌ [FAILED] Client package installation failed. Code: {code}, Error: {err or out}")
            AnsibleRunner.save_execution_log(logs, prefix="nfs_config_fail")
            return False, logs
        logs.append(f"Success: {out.strip()}")

        # Step 9: Create Mount Directory
        logs.append("\nTASK [9. Create Client Mount Directory] ***************************************")
        cmd = f"mkdir -p {mount_dir}"
        logs.append(f"Executing: {cmd}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=client_host, target_user=client_user, target_password=client_pass,
            command=cmd
        )
        if not ok or code != 0:
            logs.append(f"❌ [FAILED] Client directory creation failed. Code: {code}, Error: {err or out}")
            AnsibleRunner.save_execution_log(logs, prefix="nfs_config_fail")
            return False, logs
        logs.append(f"Success: Mount point {mount_dir} created.")

        # Step 10: Backup Client fstab
        logs.append("\nTASK [10. Backup Client /etc/fstab] ********************************************")
        cmd = "cp /etc/fstab /etc/fstab.bak"
        logs.append(f"Executing: {cmd}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=client_host, target_user=client_user, target_password=client_pass,
            command=cmd
        )
        if not ok or code != 0:
            logs.append(f"❌ [FAILED] Client fstab backup failed. Code: {code}, Error: {err or out}")
            AnsibleRunner.save_execution_log(logs, prefix="nfs_config_fail")
            return False, logs
        logs.append("Success: /etc/fstab.bak created on client.")

        # Step 11: Update Client fstab
        logs.append("\nTASK [11. Update Client /etc/fstab] ********************************************")
        fstab_entry = f"{server_host}:{export_dir} {mount_dir} nfs defaults 0 0"
        cmd = f"grep -qF '{mount_dir}' /etc/fstab || echo '{fstab_entry}' >> /etc/fstab"
        logs.append(f"Executing: {cmd}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=client_host, target_user=client_user, target_password=client_pass,
            command=cmd
        )
        if not ok or code != 0:
            logs.append(f"❌ [FAILED] Client fstab update failed. Code: {code}, Error: {err or out}")
            AnsibleRunner.save_execution_log(logs, prefix="nfs_config_fail")
            return False, logs
        logs.append(f"Success: Appended {fstab_entry}")

        # Step 12: Mount Share
        logs.append("\nTASK [12. Mount NFS share on Client] *******************************************")
        cmd = "mount -a"
        logs.append(f"Executing: {cmd}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=client_host, target_user=client_user, target_password=client_pass,
            command=cmd
        )
        if not ok or code != 0:
            logs.append(f"❌ [FAILED] Mount failed on client. Code: {code}, Error: {err or out}")
            AnsibleRunner.save_execution_log(logs, prefix="nfs_config_fail")
            return False, logs
        logs.append("Success: Share mounted.")

        # Step 13: Verify Mount
        logs.append("\nTASK [13. Verify Mount on Client] **********************************************")
        cmd = f"df -h {mount_dir} && mount | grep {mount_dir}"
        logs.append(f"Executing: {cmd}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=client_host, target_user=client_user, target_password=client_pass,
            command=cmd
        )
        if ok:
            logs.extend(out.splitlines())
            if err:
                logs.append(f"[STDERR] {err}")
        else:
            logs.append(f"❌ [ERROR] Client mount verification failed: {err}")
            AnsibleRunner.save_execution_log(logs, prefix="nfs_config_fail")
            return False, logs

        log_file, log_path = AnsibleRunner.save_execution_log(logs, prefix="nfs_config")
        return True, {
            "log_file": log_file,
            "stdout": out,
            "logs": logs
        }

    @classmethod
    def telnet_check_on_vm(cls, jump_host, target_host, target_user, target_password, dest_host, dest_port, timeout=3):
        try:
            timeout = int(timeout)
        except Exception:
            timeout = 3
        try:
            dest_port = int(dest_port)
        except Exception:
            dest_port = 22

        jump_cfg = AnsibleRunner.get_jump_config(jump_host)
        jump_ip = jump_cfg["jump_host"]
        jump_user = jump_cfg["jump_user"]
        jump_pass = jump_cfg["jump_password"]

        logs = [
            "================================================================================",
            "[STATIC OPS ENGINE] REMOTE TCP CONNECTIVITY DIAGNOSTIC",
            "--------------------------------------------------------------------------------",
            f"Timestamp         : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Source VM (Target): {target_host} (user: {target_user})",
            f"Probing Target    : {dest_host}:{dest_port}",
            f"Timeout limit     : {timeout} seconds",
            "================================================================================",
            "CONNECTING TO SOURCE VM VIA JUMP HOST...",
        ]

        cmd = f"python3 -c \"import socket, time; t0=time.time(); s=socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout({timeout}); s.connect(('{dest_host}', {dest_port})); print('SUCCESS', round((time.time()-t0)*1000, 2))\""
        
        ok, code, stdout, stderr = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=target_host, target_user=target_user, target_password=target_password,
            command=cmd, timeout=timeout + 3
        )

        if ok and code == 0 and "SUCCESS" in stdout:
            parts = stdout.strip().split()
            latency = parts[1] if len(parts) > 1 else "unknown"
            logs.append(f"   [OK] Connection from {target_host} to {dest_host}:{dest_port} successful!")
            logs.append(f"   Latency: {latency} ms")
            
            log_file, log_path = AnsibleRunner.save_execution_log(logs, prefix="telnet_check")
            return True, {
                "reachable": True,
                "latency_ms": latency,
                "logs": logs,
                "log_file": log_file
            }
        else:
            err_msg = stderr.strip() if stderr else stdout.strip()
            if not err_msg:
                err_msg = "Connection timed out or host unreachable."
            logs.append(f"❌ [FAILED] Connection from {target_host} to {dest_host}:{dest_port} failed.")
            logs.append(f"   Error: {err_msg}")
            
            log_file, log_path = AnsibleRunner.save_execution_log(logs, prefix="telnet_check")
            return False, {
                "reachable": False,
                "latency_ms": None,
                "error": err_msg,
                "logs": logs,
                "log_file": log_file
            }
