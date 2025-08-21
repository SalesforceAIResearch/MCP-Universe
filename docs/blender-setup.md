# Blender MCP Server Setup Guide

This guide will help you set up the Blender MCP server integration within the MCP-Universe project.

## Acknowledgments

This Blender MCP integration is built upon the excellent work by [@ahujasid](https://github.com/ahujasid) and the [blender-mcp project](https://github.com/ahujasid/blender-mcp). We extend our gratitude for their contribution to the MCP ecosystem.

## Overview

The Blender MCP server enables LLMs to directly interact with and control Blender through the Model Context Protocol. This integration allows for:

- **AI-assisted 3D modeling**: Create and modify 3D objects through natural language
- **Scene manipulation**: Control lighting, cameras, and materials
- **Asset integration**: Download and use assets from Poly Haven
- **Code execution**: Run arbitrary Python code in Blender
- **Real-time collaboration**: Two-way communication between LLMs and Blender

## Prerequisites

Before starting, ensure you have:

- **Blender 3.0 or newer** installed
- **Python 3.10 or newer**
- **uv package manager** (required for MCP server management)

### Installing uv Package Manager

**For macOS:**
```bash
brew install uv
```

**For Windows:**
```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```
Then add to PATH:
```cmd
set Path=C:\Users\%USERNAME%\.local\bin;%Path%
```

**For Linux/Other platforms:**
See the [official uv installation guide](https://docs.astral.sh/uv/getting-started/installation/)

⚠️ **Important**: Do not proceed without installing uv first!

## Installation Steps

### Step 1: Download the Blender Addon

Download the Blender addon from our project:
- **Addon file**: [Download from Google Drive](https://drive.google.com/file/d/1o3SCsPQUXKf7y3anuyvhwvN5Zd1xHcR0/view?usp=drive_link)

### Step 2: Install the Blender Addon

1. Open **Blender**
2. Navigate to **Edit > Preferences > Add-ons**
3. Click **"Install..."** button
4. Select the downloaded `addon.py` file
5. **Enable the addon** by checking the box next to "Interface: Blender MCP"
6. The addon should now appear in your Blender interface

### Step 3: Configure MCP Server

#### For Claude Desktop Integration

1. Open Claude Desktop
2. Go to **Claude > Settings > Developer > Edit Config**
3. Edit `claude_desktop_config.json` and add the following configuration:

```json
{
    "mcpServers": {
        "blender": {
            "command": "uvx",
            "args": [
                "blender-mcp"
            ]
        }
    }
}
```

#### For Cursor Integration

**Option 1: Global MCP Server**
1. Go to **Settings > MCP**
2. Click **"Add new global MCP server"**
3. Use the following configuration:

```json
{
    "mcpServers": {
        "blender": {
            "command": "uvx",
            "args": [
                "blender-mcp"
            ]
        }
    }
}
```

**Option 2: Project-specific Server**
1. Create `.cursor/mcp.json` in your project root
2. Add the same configuration as above

**For Windows Cursor users:**
Use this configuration instead:
```json
{
    "mcpServers": {
        "blender": {
            "command": "cmd",
            "args": [
                "/c",
                "uvx",
                "blender-mcp"
            ]
        }
    }
}
```

⚠️ **Note**: Only run one instance of the MCP server (either Claude Desktop OR Cursor), not both simultaneously.

## Security Considerations

⚠️ **Important Security Notes:**

- The Blender MCP server can execute arbitrary Python code in Blender
- Always save your work before using code execution features
- Use with caution in production environments
- Consider the implications of automated asset downloads
