# Notion

This guide walks you through preparing your Notion environment for MCPMark and authenticating the CLI tools.

> Note: Set your Notion app and workspace interface language to English. We use Playwright for browser automation and our locator logic relies on raw English text in the UI. Non-English interfaces can cause element selection to fail.

## 1 · Set up Notion Environment

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

## 2 · Authenticate with Notion

### Quick Start

```bash
# First, install Playwright and the browser binaries
pip install playwright
playwright install

# Navigate to the prepare scripts directory
cd /Users/vichen/school/MCP/MCP-Universe/mcpmark/prepare_scripts

# Run the login helper (GUI mode - recommended)
# Session state will be saved to: MCP-Universe/notion_state.json
./notion_login.sh gui

# Or use headless mode (requires email + verification code)
./notion_login.sh headless
```

### Alternative Methods

**Using Python script directly:**
```bash
cd /Users/vichen/school/MCP/MCP-Universe/mcpmark/prepare_scripts

# GUI mode with Firefox (default)
python3 notion_login.py

# GUI mode with Chromium
python3 notion_login.py --browser chromium

# Headless mode
python3 notion_login.py --headless

# Custom output location
python3 notion_login.py --output ~/notion_session.json
```

**Using the original method (deprecated):**
```bash
python -m mcpuniverse.benchmark.mcpmark_deps.src.mcp_services.notion.notion_login_helper --browser chromium
```

### 📖 Detailed Documentation

For complete usage instructions, troubleshooting, and advanced options, see:
- [Notion Login README](../prepare_scripts/NOTION_LOGIN_README.md)

The verification script will tell you which browser is working properly. The pipeline defaults to using **chromium**. Our pipeline has been **fully tested on macOS and Linux**.

## 3. Running Notion Tasks

1. Configure environment variables: make sure the following service credentials are added in `.mcp_env`.
```env
## Notion
SOURCE_NOTION_API_KEY="your-source-notion-api-key"   # For Source Hub (templates)
EVAL_NOTION_API_KEY="your-eval-notion-api-key"       # For Eval Hub (active evaluation)
SOURCE_PARENT_PAGE_TITLE="MCPMark Source Hub"        # Source hub page name (exact match)
EVAL_PARENT_PAGE_TITLE="MCPMark Eval Hub"           # Must match the name of the empty page you created in Eval Hub
PLAYWRIGHT_BROWSER="chromium" # default to chromium, you can also choose firefox
PLAYWRIGHT_HEADLESS="True"
```

2. For single task or task group, run 
```bash
python -m pipeline --exp-name EXPNAME --mcp notion --tasks NOTIONTASK --models MODEL --k K
```
Here *EXPNAME* refers to customized experiment name, *NOTIONTASK* refers to the notion task or task group selected (see [Task Page](../datasets/task.md) for specific task information), *MODEL* refers to the selected model (see [Introduction Page](../introduction.md) for model supported), *K* refers to the time of independent experiments.
