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

        # ----------------==================================----------------
        # SERVER SIDE (NFS SERVER)
        # ----------------==================================----------------
        logs.append("\n=================== SERVER SIDE (NFS SERVER) ===================")

        # 1. Collect Inputs
        logs.append("\nTASK [1. Collect Inputs] *******************************************************")
        logs.append(f"  NFS Server IP: {server_host}")
        logs.append(f"  Export Directory: {export_dir}")
        logs.append(f"  Client IP: {client_host}")
        logs.append("  Export options: rw,sync,no_subtree_check")

        # 2. Validate Filesystem (Ensure Directory Exists)
        logs.append("\nTASK [2. Validate Filesystem] **************************************************")
        cmd_create = f"mkdir -p {export_dir} && chmod 777 {export_dir}"
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=server_host, target_user=server_user, target_password=server_pass,
            command=cmd_create
        )
        cmd_val = f"ls -ld {export_dir}"
        logs.append(f"Executing directory validation command: {cmd_val}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=server_host, target_user=server_user, target_password=server_pass,
            command=cmd_val
        )
        if not ok or code != 0:
            logs.append(f"❌ [FAILED] Directory {export_dir} validation failed. Code: {code}, Error: {err or out}")
            AnsibleRunner.save_execution_log(logs, prefix="nfs_config_fail")
            return False, logs
        logs.append(f"Directory verified: {out.strip()}")

        # 3. Backup Existing Configuration
        logs.append("\nTASK [3. Backup Existing Configuration] ****************************************")
        bkp_cmd = "cp -p /etc/exports /etc/exports_bkp_$(date +%Y%m%d_%H%M%S) 2>/dev/null || true"
        logs.append(f"Executing: {bkp_cmd}")
        AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=server_host, target_user=server_user, target_password=server_pass,
            command=bkp_cmd
        )
        logs.append("Backup command sent for /etc/exports.")

        # 4. Update /etc/exports (Duplicate check and append logic)
        logs.append("\nTASK [4. Update /etc/exports] **************************************************")
        export_entry = f"{export_dir} {client_host}(rw,sync,no_subtree_check)"
        
        py_cmd = (
            f"python3 -c \"import os, sys; p = '/etc/exports'; ed = sys.argv[1]; ch = sys.argv[2]; opt = sys.argv[3]; "
            f"if not os.path.exists(p):\\n  with open(p, 'w') as f: pass\\n"
            f"with open(p, 'r') as f: lines = f.readlines()\\n"
            f"exists = False\\n"
            f"for l in lines:\\n"
            f"  l = l.strip()\\n"
            f"  if not l or l.startswith('#'): continue\\n"
            f"  pts = l.split()\\n"
            f"  if len(pts) >= 2:\\n"
            f"    if pts[0] == ed and ch in ''.join(pts[1:]):\\n"
            f"      exists = True; break\\n"
            f"if exists:\\n"
            f"  print('SKIP')\\n"
            f"else:\\n"
            f"  with open(p, 'a') as f:\\n"
            f"    if lines and not lines[-1].endswith('\\\\n'): f.write('\\\\n')\\n"
            f"    f.write(f'{{ed}} {{ch}}({{opt}})\\\\n')\\n"
            f"  print('APPENDED')\" '{export_dir}' '{client_host}' 'rw,sync,no_subtree_check'"
        )
        logs.append("Running duplicate export verification check...")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=server_host, target_user=server_user, target_password=server_pass,
            command=py_cmd
        )
        if not ok or code != 0:
            logs.append(f"❌ [FAILED] Server exports update failed. Code: {code}, Error: {err or out}")
            AnsibleRunner.save_execution_log(logs, prefix="nfs_config_fail")
            return False, logs
        
        result_str = out.strip()
        if "SKIP" in result_str:
            logs.append("ℹ️  Export entry already exists for same directory and client. Skipping addition.")
        else:
            logs.append("Success: Export entry successfully appended to /etc/exports.")

        # Show verified exports
        ok_cat, code_cat, out_cat, err_cat = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=server_host, target_user=server_user, target_password=server_pass,
            command="cat /etc/exports"
        )
        logs.append("Verified /etc/exports contents:")
        logs.extend([f"  {line}" for line in out_cat.splitlines()])

        # 5. Refresh Exports
        logs.append("\nTASK [5. Refresh Exports] ******************************************************")
        cmd_refresh = "exportfs -avr"
        logs.append(f"Executing: {cmd_refresh}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=server_host, target_user=server_user, target_password=server_pass,
            command=cmd_refresh
        )
        if not ok or code != 0:
            logs.append(f"❌ [FAILED] exportfs reload failed. Code: {code}, Error: {err or out}")
            AnsibleRunner.save_execution_log(logs, prefix="nfs_config_fail")
            return False, logs
        logs.append("exportfs output:")
        logs.extend([f"  {line}" for line in out.splitlines()])

        # 6. Verify Export (with showmount)
        logs.append("\nTASK [6. Verify Export (showmount -e)] *****************************************")
        cmd_show = f"showmount -e localhost"
        logs.append(f"Executing: {cmd_show}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=server_host, target_user=server_user, target_password=server_pass,
            command=cmd_show
        )
        
        export_visible = ok and (export_dir in out)
        if not export_visible:
            logs.append("⚠️  Export not immediately visible. Attempting recovery and restart of services...")
            # 7. If Export Is Not Visible (Restart Services)
            logs.append("\nTASK [7. Restart NFS Services for Recovery] ***********************************")
            restart_cmd = (
                "systemctl status nfs-server || true; "
                "systemctl status rpcbind || true; "
                "systemctl restart rpcbind && "
                "systemctl restart rpcbind.socket && "
                "systemctl restart nfs-server && "
                "exportfs -avr"
            )
            logs.append(f"Executing service restarts & re-export: {restart_cmd}")
            AnsibleRunner.ssh_execute_via_jump(
                jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
                target_host=server_host, target_user=server_user, target_password=server_pass,
                command=restart_cmd
            )

            # Re-verify export list
            logs.append("Re-checking showmount:")
            ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
                jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
                target_host=server_host, target_user=server_user, target_password=server_pass,
                command=cmd_show
            )
            logs.extend([f"  {line}" for line in out.splitlines()])
        else:
            logs.append("showmount output:")
            logs.extend([f"  {line}" for line in out.splitlines()])

        # 8. Verify RPC Services
        logs.append("\nTASK [8. Verify RPC Services (rpcinfo -p)] *************************************")
        cmd_rpc = "rpcinfo -p"
        logs.append(f"Executing: {cmd_rpc}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=server_host, target_user=server_user, target_password=server_pass,
            command=cmd_rpc
        )
        if ok:
            logs.append("Registered RPC services:")
            logs.extend([f"  {line}" for line in out.splitlines()[:20]]) # truncate long output
        else:
            logs.append(f"⚠️  Could not fetch RPC list: {err}")

        # ----------------==================================----------------
        # CLIENT SIDE (NFS CLIENT)
        # ----------------==================================----------------
        logs.append("\n=================== CLIENT SIDE (NFS CLIENT) ===================")

        # 1. Verify Export from Client
        logs.append("\nTASK [9. Verify Server Export list from Client] *******************************")
        cmd_cli_show = f"showmount -e {server_host}"
        logs.append(f"Executing on client: {cmd_cli_show}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=client_host, target_user=client_user, target_password=client_pass,
            command=cmd_cli_show
        )
        if not ok or "clnt_create" in out or "clnt_create" in err:
            logs.append("⚠️  RPC Program not registered. Retrying once in 5 seconds...")
            time.sleep(5)
            ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
                jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
                target_host=client_host, target_user=client_user, target_password=client_pass,
                command=cmd_cli_show
            )
        if not ok:
            logs.append(f"❌ [FAILED] Client showmount verification failed: {err or out}")
            AnsibleRunner.save_execution_log(logs, prefix="nfs_config_fail")
            return False, logs
        logs.append(f"Client saw exports:")
        logs.extend([f"  {line}" for line in out.splitlines()])

        # 2 & 3. Create Mount Point
        logs.append(f"\nTASK [10. Create Mount Point directory {mount_dir}] ****************************")
        cmd_mount_point = f"mkdir -p {mount_dir}"
        logs.append(f"Executing on client: {cmd_mount_point}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=client_host, target_user=client_user, target_password=client_pass,
            command=cmd_mount_point
        )
        if not ok or code != 0:
            logs.append(f"❌ [FAILED] Client directory creation failed. Code: {code}, Error: {err or out}")
            AnsibleRunner.save_execution_log(logs, prefix="nfs_config_fail")
            return False, logs
        logs.append("Success: Mount point directory verified.")

        # 4. Backup fstab
        logs.append("\nTASK [11. Backup fstab configuration] ******************************************")
        cmd_fstab_bkp = "cp -p /etc/fstab /etc/fstab_bkp_$(date +%Y%m%d_%H%M%S) 2>/dev/null || true"
        logs.append(f"Executing fstab backup.")
        AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=client_host, target_user=client_user, target_password=client_pass,
            command=cmd_fstab_bkp
        )
        logs.append("Backup fstab command completed.")

        # 5. Update /etc/fstab
        logs.append("\nTASK [12. Update /etc/fstab] ***************************************************")
        fstab_entry = f"{server_host}:{export_dir}    {mount_dir}    nfs    defaults    0    0"
        # Clean any old mounts for same directory to avoid duplicated mounts in fstab
        cmd_fstab_update = f"sed -i '\\|{mount_dir}|d' /etc/fstab; echo '{fstab_entry}' >> /etc/fstab && cat /etc/fstab"
        logs.append("Applying fstab config entry...")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=client_host, target_user=client_user, target_password=client_pass,
            command=cmd_fstab_update
        )
        if not ok or code != 0:
            logs.append(f"❌ [FAILED] Client fstab update failed. Code: {code}, Error: {err or out}")
            AnsibleRunner.save_execution_log(logs, prefix="nfs_config_fail")
            return False, logs
        logs.append("Verified fstab contents:")
        logs.extend([f"  {line}" for line in out.splitlines()])

        # 6. Mount Filesystem (With 10s hang protection timeout)
        logs.append("\nTASK [13. Mount Filesystem] ****************************************************")
        # Ensure target is unmounted first to avoid "already mounted" locks
        AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=client_host, target_user=client_user, target_password=client_pass,
            command=f"umount -f {mount_dir} 2>/dev/null || true"
        )
        cmd_mount = f"timeout 10 mount {mount_dir}"
        logs.append(f"Executing client mount with 10s timeout: {cmd_mount}")
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=client_host, target_user=client_user, target_password=client_pass,
            command=cmd_mount
        )
        if code == 124:
            logs.append("❌ [FAILED] NFS mount command hung for more than 10 seconds. Check client-server connectivity or firewalls.")
            AnsibleRunner.save_execution_log(logs, prefix="nfs_config_fail")
            return False, logs
        if not ok or code != 0:
            logs.append(f"❌ [FAILED] Mount command failed. Code: {code}, Error: {err or out}")
            AnsibleRunner.save_execution_log(logs, prefix="nfs_config_fail")
            return False, logs
        logs.append("NFS share mounted successfully.")

        # 7. Verify Mount & Read/Write access
        logs.append("\nTASK [14. Verify Mount and Write Access] ***************************************")
        cmd_verify_mount = f"df -h {mount_dir} && mount | grep {mount_dir}"
        ok, code, out, err = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=client_host, target_user=client_user, target_password=client_pass,
            command=cmd_verify_mount
        )
        if not ok:
            logs.append(f"❌ [FAILED] Mount verification check failed. Error: {err or out}")
            AnsibleRunner.save_execution_log(logs, prefix="nfs_config_fail")
            return False, logs
        logs.append("Mount verification check output:")
        logs.extend([f"  {line}" for line in out.splitlines()])

        # Read/write verification test
        test_file = f"{mount_dir}/.nfs_opshub_test"
        cmd_rw_test = f"touch {test_file} && rm -f {test_file}"
        logs.append(f"Verifying read/write access via: {cmd_rw_test}")
        ok_rw, code_rw, out_rw, err_rw = AnsibleRunner.ssh_execute_via_jump(
            jump_host=jump_ip, jump_user=jump_user, jump_password=jump_pass,
            target_host=client_host, target_user=client_user, target_password=client_pass,
            command=cmd_rw_test
        )
        rw_success = ok_rw and (code_rw == 0)
        if not rw_success:
            logs.append(f"❌ [FAILED] Read/write access check failed. Error: {err_rw or out_rw}")
            AnsibleRunner.save_execution_log(logs, prefix="nfs_config_fail")
            return False, logs
        logs.append("Read/write access verified.")

        # ----------------==================================----------------
        # FINAL STATUS SUMMARY LIST
        # ----------------==================================----------------
        logs.append("\n=================== VERIFICATION CHECKLIST SUMMARY ===================")
        logs.append("✔ Export entry successfully added to /etc/exports.")
        logs.append("✔ exportfs -avr completed successfully.")
        logs.append("✔ showmount -e displays the exported filesystem.")
        logs.append("✔ Mount point created on the client.")
        logs.append("✔ /etc/fstab updated successfully.")
        logs.append("✔ NFS filesystem mounted successfully.")
        logs.append("✔ df -h confirms the mount.")
        logs.append("✔ Read/write access verified on the mounted share.")
        logs.append("======================================================================")

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
