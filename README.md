# OpsHub — Central Automation Dashboard

OpsHub is a clean, modern web application designed for running Ansible playbooks, executing ad-hoc terminal commands, provisioning NFS shares, diagnosing disks, and performing controlled reboots via SSH jump host proxies.

---

## 🚀 Migration & Deployment on Another Linux Setup

If you are migrating OpsHub to a new hosted Linux setup (e.g. Ubuntu, RHEL, or Rocky Linux), use the following steps to configure the application for your new infrastructure.

### 1. Requirements & Prerequisites

Ensure the following packages are installed on the hosting server:
- **Python 3.8+** (Python 3.9 or 3.10 is recommended)
- **pip** (Python package installer)
- **Git** (for version control)

#### For Ubuntu/Debian:
```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv git -y
```

#### For RHEL/Rocky Linux/AlmaLinux:
```bash
sudo dnf install python3 python3-pip git -y
```

---

### 2. Configuration Customization

Before launching, you must update the hardcoded settings and fallback configurations to match your actual server network:

1. **POD Jump Hosts (`app/data/pods.json`):**
   Update this file with the correct IP addresses (`jump_host`), SSH ports (`ssh_port`), and authentication details for your specific Jump Hosts.
   
2. **Ansible Inventories (`inventory/dev_inventory.ini`):**
   Update the host list and target VM IPs configured inside the inventory file to match the managed machines on your new infrastructure.

3. **Frontend Forms (`app/templates/execute.html`):**
   Replace the default input fallback IPs (e.g., `192.168.209.136` or `192.168.209.135`) with empty values (`value=""` and custom placeholders) or your environment's default target VMs.

4. **Audit Header Labels:**
   Modify the default labels inside `app/services/ansible_runner.py` and `app/services/reboot_runner.py` to display your new central server IP instead of `192.168.209.137`.

---

### 3. Installation & Setup

1. **Clone the Repository:**
   ```bash
   git clone https://github.com/ResolvDotConf0106/OpsHub.git
   cd OpsHub
   ```

2. **Create a Virtual Environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install Dependencies:**
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **Directory & File Permissions:**
   OpsHub stores log archives, SQLite databases, and dynamic inventory files inside the project structure. Ensure the user running the Flask server has write permissions to the folder:
   ```bash
   chmod -R 755 .
   ```

5. **Initialize Database:**
   OpsHub automatically initializes its SQLite database schema on startup. A default Administrator account is seeded:
   - **Username:** `admin`
   - **Password:** `admin123`

---

### 4. Production Hosting Setup (Recommended)

For production deployment, instead of running `python run.py`, run the application under a WSGI server like **Gunicorn** behind an **Nginx** reverse proxy:

1. **Install Gunicorn:**
   ```bash
   pip install gunicorn
   ```

2. **Configure Systemd Service:**
   Create `/etc/systemd/system/opshub.service`:
   ```ini
   [Unit]
   Description=OpsHub Enterprise Portal
   After=network.target

   [Service]
   User=your-ssh-user
   WorkingDirectory=/path/to/OpsHub
   ExecStart=/path/to/OpsHub/venv/bin/gunicorn --workers 4 --bind 127.0.0.1:5000 run:app
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```
   
   Start and enable the service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl start opshub
   sudo systemctl enable opshub
   ```

3. **Configure Nginx Proxy:**
   Create an Nginx configuration file pointing to Gunicorn:
   ```nginx
   server {
       listen 80;
       server_name your_domain_or_ip;

       location / {
           proxy_pass http://127.0.0.1:5000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       }
   }
   ```

---

## 🛠 Technical Highlights

- **Dynamic Search Filtering:** Integrated dynamic Javascript filtering in the top navbar that auto-adapts to search POD cards, user lists, log indices, or history tables based on the visited route.
- **Controlled Reboot Autopilot:** Full execution pipeline that checks system status, restarts target nodes, polls target SSH connectivity, and validates services after boot completes.
- **10s Hang Protection:** Direct mount triggers include hang protection wrappers to instantly capture and alert on connection timeouts.
- **Pure Python SSH Tunnelling:** Pure-python SSH jump host proxy tunnelling handled natively via `paramiko` to operate cleanly without local keys or system requirements.
