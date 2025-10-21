#!/bin/bash
# Run localhost browser automation benchmark test

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Cleanup function
cleanup() {
    echo -e "\n${GREEN}Cleaning up...${NC}"
    if [ ! -z "$SERVER_PID" ]; then
        echo "Stopping web server (PID: $SERVER_PID)"
        kill $SERVER_PID 2>/dev/null || true
        wait $SERVER_PID 2>/dev/null || true
    fi
}

# Set trap to cleanup on exit
trap cleanup EXIT INT TERM

# Start web server
echo -e "${GREEN}Starting web server on http://localhost:8080${NC}"
python3 simple_test_server.py 8080 &
# python3 browser_agent_eval/app.py 8080 &
SERVER_PID=$!
echo "Server PID: $SERVER_PID"

# Wait for server to start
echo "Waiting for server to be ready..."
sleep 3

# Verify server is running
if ! curl -s http://localhost:8080/ > /dev/null; then
    echo -e "${RED}ERROR: Server failed to start${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Server is running${NC}\n"

export SQLITE_TRACER_COLLECTOR_ADDRESS=/home/ec2-user/git/mcp_attacks/MCP-Universe
# Run the benchmark
echo -e "${GREEN}Running benchmark...${NC}"
python3 run_agent_benchmark.py --benchmark_path mcpuniverse/benchmark/configs/web_browsing/memory_exfil_benchmark.yaml

echo -e "\n${GREEN}Benchmark completed!${NC}"
