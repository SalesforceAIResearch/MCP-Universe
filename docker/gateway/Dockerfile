# Dockerfile for MCPUniverse MCP Gateway
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies required for MCP gateway
RUN apt-get update && apt-get install -y \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy source code
COPY . .

# Install MCPUniverse package
RUN pip install -e .

# Create non-root user for security
RUN groupadd -r mcpgateway && useradd -r -g mcpgateway mcpgateway && \
    chown -R mcpgateway:mcpgateway /app

# Switch to non-root user
USER mcpgateway

# Expose the default gateway port
EXPOSE 8000

# Default command to run the MCP gateway
CMD ["python", "-m", "mcpuniverse.mcp.gateway", "--port", "8000", "--mode", "stdio"]