#!/bin/bash
#
# Playwright WebArena Setup Script
# =================================
#
# This script prepares the WebArena environments for Playwright testing.
#
# Usage:
#   ./setup_playwright_webarena.sh              # Setup all environments
#   ./setup_playwright_webarena.sh --cmu        # Use CMU server instead of Archive.org
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "🚀 Playwright WebArena Setup"
echo "=========================================="
echo ""

# Change to project root
cd "$PROJECT_ROOT"

# Check if Python 3 is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: python3 is not installed"
    exit 1
fi

# Check if wget is available
if ! command -v wget &> /dev/null; then
    echo "❌ Error: wget is not installed"
    echo "   Install with: brew install wget (macOS) or apt install wget (Linux)"
    exit 1
fi

# Parse arguments
DOWNLOAD_SOURCE="archive"
if [[ "$1" == "--cmu" ]]; then
    DOWNLOAD_SOURCE="cmu"
fi

# Run the preparation script
python3 mcpmark/prepare_scripts/prepare_playwright_webarena.py --download-source "$DOWNLOAD_SOURCE"

exit_code=$?

if [ $exit_code -eq 0 ]; then
    echo ""
    echo "✅ Setup complete!"
else
    echo ""
    echo "❌ Setup failed. Please check the errors above."
fi

exit $exit_code

