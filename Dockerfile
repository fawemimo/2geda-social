# 1. Upgraded base image to support Django 6.0+
FROM python:3.12-slim

# Set work directory
WORKDIR /app

# Install system dependencies (Updated for Debian Trixie/Python 3.14)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
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
    libxml2 \
    libjpeg62-turbo-dev \
    zlib1g \
    netcat-traditional && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/

# Install Python dependencies
# RUN pip install --upgrade pip && pip install -r requirements.txt
RUN pip install --no-cache-dir --force-reinstall -r requirements.txt

# Copy application files
COPY . /app/

# Expose the port
EXPOSE 8000