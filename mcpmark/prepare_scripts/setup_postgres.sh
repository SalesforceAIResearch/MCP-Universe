#!/bin/bash
#
# PostgreSQL Setup Script for MCPMark Benchmarks
# ==============================================
#
# This script prepares the PostgreSQL environment for running benchmarks.
#
# Usage:
#   ./setup_postgres.sh           # Setup all databases
#   ./setup_postgres.sh --force   # Force re-download
#   ./setup_postgres.sh chinook   # Setup specific database
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "🚀 PostgreSQL Setup for MCPMark Benchmarks"
echo "=========================================="
echo ""

# Change to project root
cd "$PROJECT_ROOT"

# Check if Python 3 is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: python3 is not installed"
    exit 1
fi

# Run the preparation script
python3 mcpmark/prepare_scripts/prepare_postgres.py "$@"

exit_code=$?

if [ $exit_code -eq 0 ]; then
    echo ""
    echo "✅ Setup complete! You can now run:"
    echo "   python tests/benchmark/test_benchmark_mcpmark_postgres.py"
else
    echo ""
    echo "❌ Setup failed. Please check the errors above."
fi

exit $exit_code

