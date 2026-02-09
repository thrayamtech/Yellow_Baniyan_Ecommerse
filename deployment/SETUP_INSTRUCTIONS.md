# Deployment Setup Instructions

## 1. Server Setup (One-time)

### Step 1: Install Gunicorn Service

Copy the service file to systemd:
```bash
sudo cp /home/ubuntu/ecom/yellow_banyan/deployment/gunicorn.service /etc/systemd/system/gunicorn.service
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable gunicorn
sudo systemctl start gunicorn
```

Check status:
```bash
sudo systemctl status gunicorn
```

### Step 2: Allow ubuntu user to restart services without password

Run this command to edit sudoers:
```bash
sudo visudo
```

Add this line at the end:
```
ubuntu ALL=(ALL) NOPASSWD: /bin/systemctl restart gunicorn, /bin/systemctl reload nginx
```

Save and exit (Ctrl+X, then Y, then Enter).

---

## 2. GitHub Secrets Setup

Go to your GitHub repository:
1. Click **Settings** → **Secrets and variables** → **Actions**
2. Add these secrets:

| Secret Name | Value |
|-------------|-------|
| `SERVER_HOST` | Your server's public IP or domain (e.g., `yellowbanyan.com` or `13.xx.xx.xx`) |
| `SERVER_USER` | `ubuntu` |
| `SSH_PRIVATE_KEY` | Your SSH private key (the content of your `.pem` file) |

### How to get SSH_PRIVATE_KEY:

If using AWS EC2, copy the content of your `.pem` file:
```bash
cat your-key.pem
```

Copy everything including:
```
-----BEGIN RSA PRIVATE KEY-----
...
-----END RSA PRIVATE KEY-----
```

---

## 3. How It Works

1. You push code to `main` branch
2. GitHub Actions automatically:
   - Connects to your server via SSH
   - Pulls the latest code
   - Installs any new dependencies
   - Runs database migrations
   - Collects static files
   - Restarts Gunicorn
   - Reloads Nginx

**Note:** The `media/` folder (product images) is NEVER touched during deployment.

---

## 4. Manual Commands (if needed)

### Restart Gunicorn manually:
```bash
sudo systemctl restart gunicorn
```

### View Gunicorn logs:
```bash
sudo journalctl -u gunicorn -f
```

### Check if Gunicorn is running:
```bash
sudo systemctl status gunicorn
```

### Reload Nginx:
```bash
sudo systemctl reload nginx
```

---

## 5. Troubleshooting

### If deployment fails:
1. Check GitHub Actions logs for errors
2. SSH into server and check Gunicorn logs:
   ```bash
   sudo journalctl -u gunicorn --since "5 minutes ago"
   ```

### If site shows 502 Bad Gateway:
```bash
sudo systemctl restart gunicorn
sudo systemctl status gunicorn
```

### If static files not loading:
```bash
cd /home/ubuntu/ecom/yellow_banyan
source venv/bin/activate
python manage.py collectstatic --noinput
```
