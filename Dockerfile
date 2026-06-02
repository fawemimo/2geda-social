# 1. Upgraded base image to support Django 6.0+
FROM python:3.14-slim

# Set work directory
WORKDIR /app

# Install system dependencies (Consolidated layers)
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
    zlib1g-dev \
    netcat-openbsd && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/

# Install Python dependencies
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy application files
COPY . /app/

# Expose the port
EXPOSE 8000