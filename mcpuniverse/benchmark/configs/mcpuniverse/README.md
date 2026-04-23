# Installation

After following the MCP-Universe framework installation instructions, please follow the below. 

Domain-Specific Services
Environment Variable	Service	Description	Setup Instructions
SERP_API_KEY	SerpAPI	Web search API for search benchmark evaluation	Get API key
GOOGLE_MAPS_API_KEY	Google Maps	Geolocation and mapping services	Setup Guide
GITHUB_PERSONAL_ACCESS_TOKEN	GitHub	Personal access token for repository operations	Token Setup
GITHUB_PERSONAL_ACCOUNT_NAME	GitHub	Your GitHub username	N/A
NOTION_API_KEY	Notion	Integration token for Notion workspace access	Integration Setup
NOTION_ROOT_PAGE	Notion	Root page ID for your Notion workspace	See configuration example below
System Paths
Environment Variable	Description	Example
BLENDER_APP_PATH	Full path to Blender executable (we used v4.4.0)	/Applications/Blender.app/Contents/MacOS/Blender
MCPUniverse_DIR	Absolute path to your MCP-Universe repository	/Users/username/MCP-Universe
Configuration Examples
Notion Root Page ID: If your Notion page URL is:

https://www.notion.so/your_workspace/MCP-Evaluation-1dd6d96e12345678901234567eaf9eff
Set NOTION_ROOT_PAGE=MCP-Evaluation-1dd6d96e12345678901234567eaf9eff

Blender Installation:

Download Blender v4.4.0 from blender.org
Install our modified Blender MCP server following the installation guide
Set the path to the Blender executable
⚠️ Security Recommendations
🔒 IMPORTANT SECURITY NOTICE

Please read and follow these security guidelines carefully before running benchmarks:

🚨 GitHub Integration: CRITICAL - We strongly recommend using a dedicated test GitHub account for benchmark evaluation. The AI agent will perform real operations on GitHub repositories, which could potentially modify or damage your personal repositories.

🔐 API Key Management:

Store API keys securely and never commit them to version control
Use environment variables or secure key management systems
Regularly rotate your API keys for enhanced security
🛡️ Access Permissions:

Grant minimal necessary permissions for each service integration
Review and limit API key scopes to only required operations
Monitor API usage and set appropriate rate limits
⚡ Blender Operations: The 3D design benchmarks will execute Blender commands that may modify or create files on your system. Ensure you have adequate backups and run in an isolated environment if necessary.


### Execution

#### Running Individual Benchmarks

Execute specific domain benchmarks using the following commands:

```bash
# Set Python path and run individual benchmarks
export PYTHONPATH=.

# Location Navigation
python tests/benchmark/mcpuniverse/test_benchmark_location_navigation.py

# Browser Automation  
python tests/benchmark/mcpuniverse/test_benchmark_browser_automation.py

# Financial Analysis
python tests/benchmark/mcpuniverse/test_benchmark_financial_analysis.py

# Repository Management
python tests/benchmark/mcpuniverse/test_benchmark_repository_management.py

# Web Search
python tests/benchmark/mcpuniverse/test_benchmark_web_search.py

# 3D Design
python tests/benchmark/mcpuniverse/test_benchmark_3d_design.py
```
