# MCPMark Integration

This directory contains the integration of [MCPMark](https://github.com/eval-sys/mcpmark/tree/24c2b31d89a4f8a43401aa8f3eded110937b0f07) into the MCP-Universe framework.

## Overview

MCPMark is a comprehensive, stress-testing MCP benchmark designed to evaluate model and agent capabilities in real-world MCP use. This integration allows you to run all MCPMark tasks within the MCP-Universe framework.

**Original Project**: https://github.com/eval-sys/mcpmark

## Structure

```
mcpmark/
├── prepare_doc/          # Environment setup guides for each service
│   ├── filesystem.md     # Filesystem service setup
│   ├── github.md         # GitHub service setup  
│   ├── notion.md         # Notion service setup
│   ├── playwright.md     # Playwright service setup
│   └── postgres.md       # PostgreSQL service setup
└── prepare_scripts/      # Helper scripts for environment preparation
```

## Environment Preparation

Before running MCPMark tasks, you need to set up the corresponding service environments. Please refer to the detailed guides in the `prepare_doc/` directory:

| Service | Setup Guide | Description |
|---------|-------------|-------------|
| **Filesystem** | [filesystem.md](prepare_doc/filesystem.md) | Zero-configuration, run directly |
| **GitHub** | [github.md](prepare_doc/github.md) | Multi-account token pooling, repository state setup |
| **Notion** | [notion.md](prepare_doc/notion.md) | Source/Eval Hub isolation, integration setup |
| **Playwright** | [playwright.md](prepare_doc/playwright.md) | Browser installation, web automation tasks |
| **PostgreSQL** | [postgres.md](prepare_doc/postgres.md) | Docker setup, sample database import |

## Running MCPMark Tasks

All MCPMark tasks have been migrated to the MCP-Universe framework and can be run using the standard test files:

### Run All Services

```bash
# GitHub tasks (23 tasks)
python tests/benchmark/test_benchmark_mcpmark_github.py

# Notion tasks (28 tasks)
python tests/benchmark/test_benchmark_mcpmark_notion.py

# Filesystem tasks (30 tasks)
python tests/benchmark/test_benchmark_mcpmark_filesystem.py

# PostgreSQL tasks (21 tasks)
python tests/benchmark/test_benchmark_mcpmark_postgres.py

# Playwright tasks (4 tasks)
python tests/benchmark/test_benchmark_mcpmark_playwright.py

# Playwright WebArena tasks (21 tasks)
python tests/benchmark/test_benchmark_mcpmark_playwright_webarena.py
```

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

Create a `.env` file in the project root with the following variables:

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

See individual service guides in `prepare_doc/` for detailed configuration instructions.