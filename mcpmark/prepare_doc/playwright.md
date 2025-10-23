# Playwright

This guide walks you through setting up WebArena environments for Playwright MCP automated testing, including Shopping, Shopping Admin, and Reddit instances.

## 1. Setup WebArena Environment (For Playwright-WebArena Tasks ONLY)

### 1.1 Download Docker Images

**⚠️ Large File Warning:** Total download size is **over 100GB**. Ensure sufficient disk space and stable network connection.

[WebArena](https://github.com/web-arena-x/webarena/tree/main/environment_docker) provides Docker images from multiple sources:

**Automated Script (Recommended):**
```bash
# Download all environments (Archive.org)
./mcpmark/prepare_scripts/setup_playwright_webarena.sh

# Or use CMU server
./mcpmark/prepare_scripts/setup_playwright_webarena.sh --cmu

# Download only specific environment
python mcpmark/prepare_scripts/prepare_playwright_webarena.py --environments shopping
```

**Manual Download:** Choose the source with best connectivity for your network

### Shopping Environment (Port 7770)
```bash
# Option 1: Google Drive (Recommended)
pip install gdown
gdown 1gxXalk9O0p9eu1YkIJcmZta1nvvyAJpA

# Option 2: Archive.org
wget https://archive.org/download/webarena-env-shopping-image/shopping_final_0712.tar

# Option 3: CMU Server
wget http://metis.lti.cs.cmu.edu/webarena-images/shopping_final_0712.tar
```

### Shopping Admin Environment (Port 7780)
```bash
# Option 1: Google Drive (Recommended)
gdown 1See0ZhJRw0WTTL9y8hFlgaduwPZ_nGfd

# Option 2: Archive.org
wget https://archive.org/download/webarena-env-shopping-admin-image/shopping_admin_final_0719.tar

# Option 3: CMU Server
wget http://metis.lti.cs.cmu.edu/webarena-images/shopping_admin_final_0719.tar
```

### Reddit Environment (Port 9999)
```bash
# Option 1: Google Drive (Recommended)
gdown 17Qpp1iu_mPqzgO_73Z9BnFjHrzmX9DGf

# Option 2: Archive.org
wget https://archive.org/download/webarena-env-forum-image/postmill-populated-exposed-withimg.tar

# Option 3: CMU Server
wget http://metis.lti.cs.cmu.edu/webarena-images/postmill-populated-exposed-withimg.tar
```

### 1.2 Deploy Environments

#### Shopping (E-commerce Site)
```bash
docker load --input shopping_final_0712.tar

# Start container
docker run --name shopping -p 7770:80 -d shopping_final_0712

# Wait for service initialization (2-3 minutes)
sleep 180

# Configure for local access
docker exec shopping /var/www/magento2/bin/magento setup:store-config:set --base-url="http://localhost:7770"
docker exec shopping mysql -u magentouser -pMyPassword magentodb -e "UPDATE core_config_data SET value='http://localhost:7770/' WHERE path IN ('web/secure/base_url', 'web/unsecure/base_url');"
docker exec shopping /var/www/magento2/bin/magento cache:flush
```

**Access**: `http://localhost:7770`  


#### Shopping Admin (Management Panel)
```bash
docker load --input shopping_admin_final_0719.tar

# Start container
docker run --name shopping_admin -p 7780:80 -d shopping_admin_final_0719

# Wait for service initialization
sleep 120

# Configure for local access
docker exec shopping_admin /var/www/magento2/bin/magento setup:store-config:set --base-url="http://localhost:7780"
docker exec shopping_admin mysql -u magentouser -pMyPassword magentodb -e "UPDATE core_config_data SET value='http://localhost:7780/' WHERE path IN ('web/secure/base_url', 'web/unsecure/base_url');"
docker exec shopping_admin php /var/www/magento2/bin/magento config:set admin/security/password_is_forced 0
docker exec shopping_admin php /var/www/magento2/bin/magento config:set admin/security/password_lifetime 0
docker exec shopping_admin /var/www/magento2/bin/magento cache:flush
```

**Access**: `http://localhost:7780/admin`  
**Admin Credentials**: `admin / admin1234`

#### Reddit (Forum)
```bash
docker load --input postmill-populated-exposed-withimg.tar

# Start container
docker run --name forum -p 9999:80 -d postmill-populated-exposed-withimg

# Wait for PostgreSQL initialization
sleep 120

# Verify service status
docker logs forum | grep "database system is ready"
curl -I http://localhost:9999
```

**Access**: `http://localhost:9999`

### 1.3 External Access Configuration

For cloud deployments (GCP, AWS, etc.), configure external access:

#### Configure Firewall (GCP Example)
```bash
# Shopping environment
gcloud compute firewall-rules create allow-shopping-7770 \
  --allow tcp:7770 --source-ranges 0.0.0.0/0

# Shopping Admin
gcloud compute firewall-rules create allow-shopping-admin-7780 \
  --allow tcp:7780 --source-ranges 0.0.0.0/0

# Reddit
gcloud compute firewall-rules create allow-reddit-9999 \
  --allow tcp:9999 --source-ranges 0.0.0.0/0
```

#### Update Base URLs for External Access
```bash
# Get external IP
EXTERNAL_IP=$(curl -s ifconfig.me)

# Shopping
docker exec shopping /var/www/magento2/bin/magento setup:store-config:set --base-url="http://${EXTERNAL_IP}:7770"
docker exec shopping mysql -u magentouser -pMyPassword magentodb -e "UPDATE core_config_data SET value='http://${EXTERNAL_IP}:7770/' WHERE path IN ('web/secure/base_url', 'web/unsecure/base_url');"
docker exec shopping /var/www/magento2/bin/magento cache:flush

# Shopping Admin  
docker exec shopping_admin /var/www/magento2/bin/magento setup:store-config:set --base-url="http://${EXTERNAL_IP}:7780"
docker exec shopping_admin mysql -u magentouser -pMyPassword magentodb -e "UPDATE core_config_data SET value='http://${EXTERNAL_IP}:7780/' WHERE path IN ('web/secure/base_url', 'web/unsecure/base_url');"
docker exec shopping_admin /var/www/magento2/bin/magento cache:flush
```

### 1.4 Alternative Access Methods (Not Verified)

#### Cloudflared Tunnel (Free & Persistent)
```bash
# Install cloudflared
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
sudo mv cloudflared-linux-amd64 /usr/local/bin/cloudflared
sudo chmod +x /usr/local/bin/cloudflared

# Create tunnels
cloudflared tunnel --url http://localhost:7770  # Shopping
cloudflared tunnel --url http://localhost:7780  # Admin
cloudflared tunnel --url http://localhost:9999  # Reddit
```

#### ngrok (Quick Sharing)
```bash
# Install ngrok
wget https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz
tar xvzf ngrok-v3-stable-linux-amd64.tgz
sudo mv ngrok /usr/local/bin

# Create tunnel (choose port)
ngrok http 7770  # For Shopping
```

## 2. Running Playwright Tasks

### 2.1 Configure Environment Variables

Add the following to your `.env` file:

```env
## Playwright Configuration
PLAYWRIGHT_BROWSER="chromium"  # Options: chromium, firefox, webkit
PLAYWRIGHT_HEADLESS="True"     # Set to "False" to see browser UI
```

### 2.2 Running Tasks

**General Playwright Tasks:**
```bash
python tests/benchmark/test_benchmark_mcpmark_playwright.py
```

**Playwright-WebArena Tasks:**
```bash
# ⚠️ Ensure WebArena environments are running
python mcpmark/prepare_scripts/check_playwright_webarena.py

# Run WebArena tasks
python tests/benchmark/test_benchmark_mcpmark_playwright_webarena.py
```

## 3. Troubleshooting

### Container Issues
```bash
# Check status
docker ps -a | grep -E "shopping|forum"

# View logs
docker logs [container_name] --tail 50

# Restart container
docker restart [container_name]
```

### Access Problems
- **First load is slow** (1-2 minutes for Magento) - this is normal
- **Ensure ports are available**: `netstat -tlnp | grep -E "7770|7780|9999"`
- **Clear cache after URL changes**: Required for Magento environments

### Reset Environment
```bash
# Stop and remove container
docker stop [container_name]
docker rm [container_name]

# Re-deploy (follow steps in Section 3)
```

## 4. Important Notes

### 4.1 General Playwright Tasks (No WebArena Required)

- ✅ **Most users can skip Section 1 entirely**
- ✅ Only browser installation needed: `playwright install chromium`
- ✅ Run: `python tests/benchmark/test_benchmark_mcpmark_playwright.py`

### 4.2 WebArena Environment (If You Downloaded)

- **Service startup time**: Allow 2-3 minutes for Magento, 1-2 minutes for Reddit
- **Memory requirements**: Ensure Docker has at least 4GB RAM allocated per container
- **Disk space**: Over 100GB free space required
- **URL configuration**: Must reconfigure base URLs after container restart for external access
- **Port assignments**: 
  - 7770: Shopping
  - 7780: Shopping Admin  
  - 9999: Reddit

### 4.3 When Do You Actually Need WebArena?

You **ONLY** need WebArena if:
- Testing AI agents on realistic e-commerce workflows
- Research on complex web interaction tasks
- Evaluating agent performance on the WebArena benchmark

You **DON'T** need WebArena for:
- General web automation testing
- Simple browser interaction tasks
- Most Playwright MCP tasks