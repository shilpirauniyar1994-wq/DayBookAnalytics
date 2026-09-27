# Base image: Official Python 3.11 slim Debian
FROM python:3.11-slim

# Prevent Python from buffering stdout/stderr and disable debconf prompts
ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PORT=8501

# Install system dependencies, curl, and Node.js 20
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    build-essential \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create standard non-root user (UID 1000)
RUN useradd -m -u 1000 user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR /app

# Install Python requirements
COPY --chown=user:user requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install Node.js dependencies for WhatsApp Multi-Device Bridge
COPY --chown=user:user whatsapp_bridge/package*.json ./whatsapp_bridge/
RUN cd whatsapp_bridge && npm install --omit=dev && cd ..

# Copy application source code
COPY --chown=user:user . .

# Ensure start script has executable permissions
RUN chmod +x start.sh

# Expose ports for web dashboard
EXPOSE 8501 8080 7860

# Switch to non-root user
USER user

# Launch all 3 services via start.sh
CMD ["./start.sh"]
