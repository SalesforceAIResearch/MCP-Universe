#!/bin/bash
#
# Notion Login Helper - Convenient wrapper script
#
# This script simplifies logging into Notion by providing easy commands.
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/notion_login.py"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper function to print colored messages
print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

# Check if Python script exists
if [ ! -f "$PYTHON_SCRIPT" ]; then
    print_error "Python script not found: $PYTHON_SCRIPT"
    exit 1
fi

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    print_error "Python 3 is not installed or not in PATH"
    exit 1
fi

# Check if Playwright is installed
if ! python3 -c "import playwright" 2>/dev/null; then
    print_error "Playwright is not installed"
    echo ""
    print_info "Please install Playwright with:"
    echo "  pip install playwright"
    echo "  playwright install"
    exit 1
fi

# Show usage if no arguments
if [ $# -eq 0 ]; then
    cat << EOF

${BLUE}🔐 Notion Login Helper${NC}
========================

Quick commands:
  ${GREEN}$0 gui${NC}         - Login with GUI browser (recommended)
  ${GREEN}$0 headless${NC}    - Login without GUI (email + code)
  ${GREEN}$0 chromium${NC}    - Login with Chromium browser

Advanced usage:
  ${GREEN}$0 custom${NC}      - Run with custom arguments
  ${GREEN}$0 help${NC}        - Show detailed help

Examples:
  # Quick GUI login with Firefox
  $0 gui

  # Headless login with Chromium
  $0 headless --browser chromium

  # Save to custom location
  $0 gui --output ~/my_notion_session.json

EOF
    exit 0
fi

# Parse command
COMMAND=$1
shift

case "$COMMAND" in
    gui)
        print_info "Starting GUI login with Firefox..."
        python3 "$PYTHON_SCRIPT" "$@"
        ;;
    
    headless)
        print_info "Starting headless login..."
        python3 "$PYTHON_SCRIPT" --headless "$@"
        ;;
    
    chromium)
        print_info "Starting login with Chromium..."
        python3 "$PYTHON_SCRIPT" --browser chromium "$@"
        ;;
    
    custom)
        print_info "Running with custom arguments..."
        python3 "$PYTHON_SCRIPT" "$@"
        ;;
    
    help|--help|-h)
        print_info "Showing detailed help..."
        python3 "$PYTHON_SCRIPT" --help
        ;;
    
    *)
        print_error "Unknown command: $COMMAND"
        echo ""
        echo "Usage: $0 {gui|headless|chromium|custom|help}"
        echo "Run '$0' without arguments for more information"
        exit 1
        ;;
esac

