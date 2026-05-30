FROM python:3.11.4-slim

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y \
    python3-dev \
    default-libmysqlclient-dev \
    build-essential \
    pkg-config \
    libffi-dev \
    libc6-dev \
    postgresql-client \
    gcc \
    git \
    libssl-dev \
    libxml2-dev \
    libjpeg-dev \
    zlib1g-dev && \
    rm -rf /var/lib/apt/lists/*

# Install netcat
RUN apt-get update && apt-get install -y netcat-openbsd

COPY requirements.txt /app/

# Install Python dependencies
RUN pip install --upgrade pip -r requirements.txt

# Copy application files
COPY . /app/

# Expose the port
EXPOSE 8000





