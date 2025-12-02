# MCPMark Integration

This directory contains the integration of [MCPMark](https://github.com/eval-sys/mcpmark/tree/24c2b31d89a4f8a43401aa8f3eded110937b0f07) into the MCP-Universe framework.

## Overview

MCPMark is a comprehensive, stress-testing MCP benchmark designed to evaluate model and agent capabilities in real-world MCP use. This integration allows you to run all MCPMark tasks within the MCP-Universe framework.

**Original Project**: https://github.com/eval-sys/mcpmark

## Environment Preparation

Before running MCPMark tasks, you need to set up the corresponding service environments. 
### Filesystem

This guide walks you through preparing your filesystem environment for MCPMark (adapted for MCP-Universe framework).

#### 1 · Configure Environment Variables

Set the `FILESYSTEM_TEST_DIR` and `FILESYSTEM_TEST_ROOT` environment variables in your `.env` file. Both should point to the same root directory:

```env
#### Filesystem
FILESYSTEM_TEST_DIR=./test_environments
FILESYSTEM_TEST_ROOT=./test_environments
```

---

**Recommended**: Use `./test_environments` (relative to third party project root)

### GitHub
This guide walks you through preparing your GitHub environment for MCPMark and authenticating the CLI tools with support for **token pooling** to mitigate rate limits.

#### 1 · Prepare An Evaluation Organization in Github

1. **Create a free GitHub Organization**  
   - In GitHub, click your avatar → **Your organizations** → **New organization**.  
   - We recommend a name like `mcpmark-eval-xxx`. (Check if there is a conflict with other organization names.)
   - This keeps all benchmark repositories isolated from your personal and work code. 
   - [![Create Org](https://i.postimg.cc/CxqJkRnj/github-create-org.png)](https://postimg.cc/k27xdXc4)
2. **Create Multiple GitHub Accounts (Recommended for Rate Limit Relief)**  
   To effectively distribute API load and avoid rate limiting, we recommend creating **2-4 additional GitHub accounts**:
   - Create new GitHub accounts (e.g., `your-name-eval-1`, `your-name-eval-2`, etc.)
   - **Important**: Add all these accounts as **Owners** to your evaluation organization
   - This allows the token pooling system to distribute requests across multiple accounts

3. **Generate Fine-Grained Personal Access Tokens (PATs) for Each Account**  
   **Repeat the following process for each GitHub account (including your main account):**
   - Navigate to *Settings → Developer settings → Personal access tokens → Fine-grained tokens*
   - Click **Generate new token**, select the evaluation organization you created
      - [![Create Token](https://i.postimg.cc/Z5SjPT82/github-create-token.png)](https://postimg.cc/Mv9yqJrm)
   - Give the token a descriptive name (e.g., *MCPMark Eval Token - Account 1*)
   - Under **Repository permissions** and **Organization permissions**, enable **All permissions** (read and write if applicable)
      - [![Token Permissions](https://i.postimg.cc/nc81ZHPr/github-token-permissions.png)](https://postimg.cc/14HFrZP1)
   - Copy the generated token and save it safely — you'll need all tokens for the next step

4. **Configure Token Pooling in `.mcp_env`**  
   In your project root, edit (or create) the `.mcp_env` file and add your tokens:
   
   **For single token (Basic setup):**
   ```env
   #### GitHub - Single Token Configuration
   GITHUB_TOKENS="your-single-token-here"
   GITHUB_EVAL_ORG="your-eval-org-name"
   ```

   **For multiple tokens (Recommended for handling rate limits):**
   ```env
   #### GitHub - Token Pooling Configuration
   GITHUB_TOKENS="token1,token2,token3,token4"
   GITHUB_EVAL_ORG="your-eval-org-name"
   ```

   **Important Notes:**
   - Replace `token1,token2,token3,token4` with your actual tokens (comma-separated, no spaces)
   - **2-4 tokens** is recommended for optimal rate limit distribution
   - All tokens must have **the same permissions** on the evaluation organization
   - The system automatically rotates between tokens to distribute API load

---

#### 2 · GitHub Rate Limits & Token Pooling Benefits

##### Understanding Rate Limits
Fine-grained tokens are subject to GitHub API rate limits:
- **Read operations**: 5,000 requests per hour per token
- **General write operations**: 80 writes per minute and 500 writes per hour per token
- **Content creation (Issues, PRs, Comments)**: **500 requests per hour per token** (Secondary Rate Limit)

##### How Token Pooling Helps
With **token pooling**, MCPMark automatically:
- **Distributes requests** across multiple tokens to multiply your rate limits
- **Rotates tokens** for each task execution to balance load
- **Handles rate limit failures** by trying the next available token
- **Ensures consistency** between agent execution and verification

##### Example: Rate Limit Multiplication
**Read Operations:**
- **Single token**: 5,000 requests/hour
- **4 tokens**: ~20,000 requests/hour total capacity

**Content Creation (Critical for MCPMark):**
- **Single token**: 500 content creation requests/hour
- **4 tokens**: ~2,000 content creation requests/hour total capacity
- **Automatic failover**: If one token hits limits, others continue working

This dramatically improves evaluation performance, especially for large task batches or frequent testing cycles. **The content creation limit is often the bottleneck**, making token pooling essential for efficient evaluations.

##### Repository Limits
MCPMark places a cap on the number of PRs and issues (≤ 50 in total) per repository to ensure reasonable evaluation times and to stay within rate limits.

---

### Notion

This guide walks you through preparing your Notion environment for MCPMark and authenticating the CLI tools.

> Note: Set your Notion app and workspace interface language to English. We use Playwright for browser automation and our locator logic relies on raw English text in the UI. Non-English interfaces can cause element selection to fail.

#### 1 · Set up Notion Environment

1. **Duplicate the MCPMark Source Pages**
   Copy the template database and pages into your workspace from the public template following this tutorial:
   [Duplicate MCPMark Source](https://painted-tennis-ebc.notion.site/MCPBench-Source-Hub-23181626b6d7805fb3a7d59c63033819).

2. **Set up the Source and Eval Hub for Environment Isolation**
   - Prepare **two separate Notion pages**:
     - **Source Hub**: Stores all the template databases/pages. Managed by `SOURCE_NOTION_API_KEY`.
     - **Eval Hub**: Only contains the duplicated templates for the current evaluation. Managed by `EVAL_NOTION_API_KEY`.
   - In Notion, create an **empty page** in your Eval Hub. The page name **must exactly match** the value you set for `EVAL_PARENT_PAGE_TITLE` in your environment variables (e.g., `MCPMark Eval Hub`).
   - Name your **Source Hub** page to match `SOURCE_PARENT_PAGE_TITLE` (default: `MCPMark Source Hub`). This is where all initial-state templates live; we enumerate this page’s first-level children by exact title.
   - In Notion's **Connections** settings:
     - Bind the integration corresponding to `EVAL_NOTION_API_KEY` to the Eval Hub parent page you just created.
     - Bind the integration corresponding to `SOURCE_NOTION_API_KEY` to your Source Hub (where the templates are stored).

3. **Create Notion Integrations & Grant Access**
   
   a. Visit [Notion Integrations](https://www.notion.so/profile/integrations) and create **two internal integrations** (one for Source Hub, one for Eval Hub).
   
   b. Copy the generated **Internal Integration Tokens** (these will be your `SOURCE_NOTION_API_KEY` and `EVAL_NOTION_API_KEY`).
   
   c. Share the **Source Hub** with the Source integration, and the **Eval Hub parent page** with the Eval integration (*Full Access*).

   [![Source Page](https://i.postimg.cc/pVjDswLH/source-page.png)](https://postimg.cc/XXVGJD5H)
   [![Create Integration](https://i.postimg.cc/vZ091M3W/create-integration.png)](https://postimg.cc/NKrLShhM)
   [![Notion API Access](https://i.postimg.cc/YCDGrRCR/api-access.png)](https://postimg.cc/CRDLJjDn)
   [![Grant Access Source](https://i.postimg.cc/2yxyPFt4/grant-access-source.png)](https://postimg.cc/n9Cnm7pz)
   [![Grant Access Eval](https://i.postimg.cc/1RM91ttc/grant-access-eval.png)](https://postimg.cc/s1QFp35v)

---

#### 2 · Authenticate with Notion

##### Quick Start

```bash
# First, install Playwright and the browser binaries
pip install playwright
playwright install

# Set PYTHONPATH to include third_party/mcpmark directory
export PYTHONPATH=/Users/vichen/school/MCP/MCP-Universe/third_party/mcpmark:$PYTHONPATH

# Then run the Notion login helper
python -m src.mcp_services.notion.notion_login_helper --browser {firefox|chromium}
```

---

### Playwright

This guide walks you through setting up WebArena environments for Playwright MCP automated testing, including Shopping, Shopping Admin, and Reddit instances.

#### 1. Setup WebArena Environment (For Playwright-WebArena Tasks ONLY)

##### 1.1 Download Docker Images

**⚠️ Large File Warning:** Total download size is **over 100GB**. Ensure sufficient disk space and stable network connection.

[WebArena](https://github.com/web-arena-x/webarena/tree/main/environment_docker) provides Docker images from multiple sources:

**Manual Download:** Choose the source with best connectivity for your network

##### Shopping Environment (Port 7770)
```bash
# Option 1: Google Drive (Recommended)
pip install gdown
gdown 1gxXalk9O0p9eu1YkIJcmZta1nvvyAJpA

# Option 2: Archive.org
wget https://archive.org/download/webarena-env-shopping-image/shopping_final_0712.tar

# Option 3: CMU Server
wget http://metis.lti.cs.cmu.edu/webarena-images/shopping_final_0712.tar
```

##### Shopping Admin Environment (Port 7780)
```bash
# Option 1: Google Drive (Recommended)
gdown 1See0ZhJRw0WTTL9y8hFlgaduwPZ_nGfd

# Option 2: Archive.org
wget https://archive.org/download/webarena-env-shopping-admin-image/shopping_admin_final_0719.tar

# Option 3: CMU Server
wget http://metis.lti.cs.cmu.edu/webarena-images/shopping_admin_final_0719.tar
```

##### Reddit Environment (Port 9999)
```bash
# Option 1: Google Drive (Recommended)
gdown 17Qpp1iu_mPqzgO_73Z9BnFjHrzmX9DGf

# Option 2: Archive.org
wget https://archive.org/download/webarena-env-forum-image/postmill-populated-exposed-withimg.tar

# Option 3: CMU Server
wget http://metis.lti.cs.cmu.edu/webarena-images/postmill-populated-exposed-withimg.tar
```

##### 1.2 Deploy Environments

######## Shopping (E-commerce Site)
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


######## Shopping Admin (Management Panel)
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

######## Reddit (Forum)
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

##### 1.3 External Access Configuration

For cloud deployments (GCP, AWS, etc.), configure external access:

######## Configure Firewall (GCP Example)
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

######## Update Base URLs for External Access
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

##### 1.4 Alternative Access Methods (Not Verified)

######## Cloudflared Tunnel (Free & Persistent)
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

######## ngrok (Quick Sharing)
```bash
# Install ngrok
wget https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz
tar xvzf ngrok-v3-stable-linux-amd64.tgz
sudo mv ngrok /usr/local/bin

# Create tunnel (choose port)
ngrok http 7770  # For Shopping
```

#### 2. Running Playwright Tasks

##### Configure Environment Variables

Add the following to your `.env` file:

```env
#### Playwright Configuration
PLAYWRIGHT_BROWSER="chromium"  # Options: chromium, firefox, webkit
PLAYWRIGHT_HEADLESS="True"     # Set to "False" to see browser UI
```

#### 3. Troubleshooting

##### Container Issues
```bash
# Check status
docker ps -a | grep -E "shopping|forum"

# View logs
docker logs [container_name] --tail 50

# Restart container
docker restart [container_name]
```

##### Access Problems
- **First load is slow** (1-2 minutes for Magento) - this is normal
- **Ensure ports are available**: `netstat -tlnp | grep -E "7770|7780|9999"`
- **Clear cache after URL changes**: Required for Magento environments

##### Reset Environment
```bash
# Stop and remove container
docker stop [container_name]
docker rm [container_name]

# Re-deploy (follow steps in Section 3)
```

#### 4. Important Notes

##### 4.1 General Playwright Tasks (No WebArena Required)

- ✅ **Most users can skip Section 1 entirely**
- ✅ Only browser installation needed: `playwright install chromium`
- ✅ Run: `python tests/benchmark/mcpmark/test_benchmark_mcpmark_playwright.py`

##### 4.2 WebArena Environment (If You Downloaded)

- **Service startup time**: Allow 2-3 minutes for Magento, 1-2 minutes for Reddit
- **Memory requirements**: Ensure Docker has at least 4GB RAM allocated per container
- **Disk space**: Over 100GB free space required
- **URL configuration**: Must reconfigure base URLs after container restart for external access
- **Port assignments**: 
  - 7770: Shopping
  - 7780: Shopping Admin  
  - 9999: Reddit

##### 4.3 When Do You Actually Need WebArena?

You **ONLY** need WebArena if:
- Testing AI agents on realistic e-commerce workflows
- Research on complex web interaction tasks
- Evaluating agent performance on the WebArena benchmark

You **DON'T** need WebArena for:
- General web automation testing
- Simple browser interaction tasks
- Most Playwright MCP tasks

---

# PostgreSQL

This guide walks you through preparing your PostgreSQL environment for MCPMark (adapted for MCP-Universe framework).

#### 1 · Configure Environment Variables

Add the following PostgreSQL credentials to your `.env` file:

```env
#### PostgreSQL Configuration
POSTGRES_ADDRESS=postgresql://postgres:password@localhost:5432
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USERNAME=postgres
POSTGRES_PASSWORD=password
```

**Note**: The database name in `POSTGRES_ADDRESS` will be automatically changed per task by `mcpuniverse/benchmark/prepares.py`.

---

#### 2 · Running PostgreSQL Tasks

```bash
python tests/benchmark/mcpmark/test_benchmark_mcpmark_postgres.py
```

---

#### 3 · Container Management

##### View Logs
```bash
docker logs mcpmark-postgres
```

##### Stop Container
```bash
docker stop mcpmark-postgres
```

##### Start Container
```bash
docker start mcpmark-postgres
```

##### Remove Container (Clean Reset)
```bash
docker stop mcpmark-postgres
docker rm mcpmark-postgres
# Then run setup again
./mcpmark/prepare_scripts/setup_postgres.sh
```

---

#### 4 · Advanced Usage

##### Force Re-download Databases

```bash
python mcpmark/prepare_scripts/prepare_postgres.py --force-download
```

##### Setup Specific Databases Only

```bash
# Single database
python mcpmark/prepare_scripts/prepare_postgres.py --databases chinook

# Multiple databases
python mcpmark/prepare_scripts/prepare_postgres.py --databases chinook employees

# All databases (default)
python mcpmark/prepare_scripts/prepare_postgres.py --databases all
```

---

#### 5 · What Gets Created

##### Files Downloaded
```
tests/data/postgres/
├── chinook.backup      # Music store database
├── employees.backup    # Employee management
├── dvdrental.backup    # DVD rental store
└── sports.backup       # Sports statistics
```

##### Docker Container
```
Name:     mcpmark-postgres
Image:    postgres:17-alpine
Port:     5432 (localhost)
User:     postgres
Password: password
```

##### Databases
```
┌──────────────┬────────┬───────────────────────────┐
│ Database     │ Tables │ Description               │
├──────────────┼────────┼───────────────────────────┤
│ chinook      │ 11     │ Music store (tracks,      │
│              │        │ albums, customers)        │
├──────────────┼────────┼───────────────────────────┤
│ employees    │ 6      │ Employee management       │
│              │        │ (salaries, departments)   │
├──────────────┼────────┼───────────────────────────┤
│ dvdrental    │ 15     │ DVD rental store          │
│              │        │ (films, rentals, payments)│
├──────────────┼────────┼───────────────────────────┤
│ sports       │ 28     │ Sports statistics         │
│              │        │ (players, teams, games)   │
└──────────────┴────────┴───────────────────────────┘
```

---


## Running MCPMark Tasks

All MCPMark tasks have been migrated to the MCP-Universe framework and can be run using the standard test files:

## Task Statistics

| Service | Tasks | Description |
|---------|-------|-------------|
| **GitHub** | 23 | Repository management, CI/CD workflows, issue tracking |
| **Notion** | 28 | Page manipulation, database operations, workspace management |
| **Filesystem** | 30 | File operations, directory management, content analysis |
| **PostgreSQL** | 21 | Database queries, schema operations, data manipulation |
| **Playwright** | 4 | Web automation, data extraction, form interaction |
| **Playwright WebArena** | 21 | E-commerce, forum, admin panel simulations |
| **Total** | **127** | Comprehensive MCP capability assessment |


## Configuration

### Required Environment Variables

The `.env` file in the project root should finally contain the following variables:

```bash
# OpenAI (Required for most tasks)
OPENAI_API_KEY="your-openai-api-key"

# GitHub (Required for GitHub tasks)
GITHUB_PERSONAL_ACCESS_TOKEN="your-github-token"
GITHUB_EVAL_ORG="your-github-org"

# Notion (Required for Notion tasks)
SOURCE_NOTION_API_KEY="your-source-notion-key"
EVAL_NOTION_API_KEY="your-eval-notion-key"

# PostgreSQL (Required for PostgreSQL tasks)
POSTGRES_HOST="localhost"
POSTGRES_PORT="5432"
POSTGRES_USERNAME="postgres"
POSTGRES_PASSWORD="your-password"

# Filesystem (Optional, defaults provided)
FILESYSTEM_TEST_ROOT="/path/to/test/root"
FILESYSTEM_TEST_DIR="/path/to/test/dir"
```
