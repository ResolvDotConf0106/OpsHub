# OpsHub — Central Automation Dashboard

OpsHub is a clean, modern web application designed for running Ansible playbooks, executing ad-hoc terminal commands, inspecting VM health, and auditing execution logs via automated SSH jump host proxies.

## Quick Start on Linux

### Prerequisites
Make sure you have Python 3 (Python 3.8+) and `pip` installed on your machine.

For Ubuntu/Debian:
```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv git -y
```

For RHEL/Rocky Linux/AlmaLinux:
```bash
sudo dnf install python3 python3-pip git -y
```

---

### Installation & Setup

1. **Clone the Repository:**
   ```bash
   git clone <your-repository-url>
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

4. **Initialize Database:**
   OpsHub automatically initializes its SQLite database schema on startup. 
   A default Administrator account is seeded:
   - **Username:** `admin`
   - **Password:** `admin123`

---

### Running the Application

To run the Flask development server locally:
```bash
python run.py
```
By default, the application will bind to `http://127.0.0.1:5000`.

---

## Features Built
1. **Interactive Metrics Dashboard:** Real-time metrics overview (Active PODs, Total Managed VMs, Running Jobs).
2. **Execute Terminal Commands & Playbooks:** Clean execution forms with ad-hoc proxy support.
3. **Playbook Viewer Modal:** Preview YAML code contents directly in the browser before running.
4. **Jobs Filter & Search:** Full table sorting by headers, search bar filtering, and status tabs (All, Running, Success, Failed).
5. **Saved Terminal Log Audit:** Dynamic time-sorting, level filtering, log search, and direct file download options.
6. **Admin Audit Log Control:** Admin panel supporting bulk checkbox selection and database deletion of audit logs.
7. **Clean Domain Authentication:** Normalized username credentials (removed suffix domain overhead).
