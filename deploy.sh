#!/bin/bash

echo "Pulling latest code..."
git pull origin main  

# Stop and remove any orphaned containers BEFORE building
echo "Stopping and removing old containers..."
if ! docker-compose down --remove-orphans; then
    echo "Failed to remove orphaned containers."
    exit 1
fi

# Build the Docker images with no cache
echo "Building Docker images with no cache..."
if ! docker-compose build --no-cache; then
    echo "Failed to build Docker images."
    exit 1
fi

# Start the services in detached mode
echo "Starting services in detached mode..."
if ! docker-compose up -d; then
    echo "Failed to start services."
    exit 1
fi

echo "🚀 Services started successfully."