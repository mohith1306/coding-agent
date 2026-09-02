FROM python:3.11-slim

# Install common development tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    wget \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install common Python packages
RUN pip install --no-cache-dir \
    pytest \
    ruff \
    black \
    mypy \
    numpy \
    pandas \
    requests \
    flask \
    django \
    fastapi \
    uvicorn

# Create non-root user
RUN useradd -m -s /bin/bash agent
USER agent
WORKDIR /workspace

# Default command
CMD ["/bin/bash"]
