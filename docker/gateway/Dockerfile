# Dockerfile for MCPUniverse MCP Gateway
FROM python:3.10-slim

# Set environment variables
# Note: do NOT set PYTHONUNBUFFERED=1. MCP stdio servers contain stray print()
# calls that corrupt the JSON-RPC stream when stdout is unbuffered.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies required for MCP gateway
RUN apt-get update && apt-get install -y \
    curl \
    git \
    build-essential \
    gnupg \
    apt-transport-https \
    && rm -rf /var/lib/apt/lists/*

# Install gcloud CLI (needed by jina-scrape-llm-summary for Vertex AI auth)
RUN curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" > /etc/apt/sources.list.d/google-cloud-sdk.list && \
    apt-get update && apt-get install -y google-cloud-cli && \
    rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy source code
COPY . .

# Install MCPUniverse package
RUN pip install -e . && \
    pip install "starlette==0.52.1" "pydantic==2.13.3"

# Create non-root user for security
RUN groupadd -r mcpgateway && useradd -r -g mcpgateway mcpgateway && \
    chown -R mcpgateway:mcpgateway /app

# Switch to non-root user
USER mcpgateway

# Expose the default gateway port
EXPOSE 8000

# Default command to run the MCP gateway
CMD ["python", "-m", "mcpuniverse.mcp.gateway", "--port", "8000", "--mode", "stdio"]