# Filesystem

This guide walks you through preparing your filesystem environment for MCPMark (adapted for MCP-Universe framework).

## 1 · Configure Environment Variables

Set the `FILESYSTEM_TEST_DIR` and `FILESYSTEM_TEST_ROOT` environment variables in your `.env` file. Both should point to the same root directory:

```env
## Filesystem
FILESYSTEM_TEST_DIR=./test_environments
FILESYSTEM_TEST_ROOT=./test_environments
```

**Recommended**: Use `./test_environments` (relative to project root)

---

## 2 · Automatic Test Environment Download

The code in `mcpuniverse/benchmark/prepares.py` automatically downloads test folders to your specified directory when the pipeline starts running.

**Downloaded Structure**:

```
./test_environments/
├── desktop/               # Desktop environment 
├── desktop_template/      # Template files for desktop
├── file_context/          # File content understanding tasks
├── file_property/         # File metadata and properties related tasks
├── folder_structure/      # Directory organization tasks
├── legal_document/        # Legal document processing
├── papers/                # Academic paper tasks
├── student_database/      # Database management tasks
├── threestudio/           # 3D Generation codebase
└── votenet/               # 3D Object Detection codebase
```

---

## 3 · Running Filesystem Tasks

```bash
python tests/benchmark/test_benchmark_mcpmark_filesystem.py
```
