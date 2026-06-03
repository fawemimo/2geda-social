#!/bin/bash

echo "Pulling latest code..."
BRANCH=${1:-master}  

git fetch origin "$BRANCH"
git checkout "$BRANCH"
git pull origin "$BRANCH"

echo "Building Docker images..."
if ! docker-compose build; then
    echo "Failed to build Docker images."
    exit 1
fi

echo "Removing orphaned containers..."
if ! docker-compose down --remove-orphans; then
    echo "Failed to remove orphaned containers."
    exit 1
fi

echo "Starting services in detached mode..."
if ! docker-compose up -d; then
    echo "Failed to start services."
    exit 1
fi

# ==========================================
# FIXED STATIC FILES PIPELINE EXTRACTION
# ==========================================
echo "Waiting a few moments for container entrypoint initialization..."
sleep 5

echo "Extracting fresh static files directly from the running web container..."
# Create a temporary directory or clear the target Nginx site assets path
rm -rf /var/www/2geda/staticfiles
mkdir -p /var/www/2geda/staticfiles

# Stream the directory out of the container directly to the host Nginx webroot
if ! docker cp $(docker compose ps -q web):/app/staticfiles/. /var/www/2geda/staticfiles/; then
    echo "❌ Failed to copy static files out of the running container."
    exit 1
fi

echo "Setting file permissions for Nginx access..."
chown -R www-data:www-data /var/www/2geda/staticfiles
chmod -R 755 /var/www/2geda/staticfiles

# Reload Nginx
echo "Reloading Nginx..."
if nginx -t && systemctl reload nginx; then
    echo "Nginx reloaded successfully."
else
    echo "Nginx reload failed."
    exit 1
fi

echo "🚀 Services started and static assets deployed successfully."

# #!/bin/bash

# echo "Pulling latest code..."
# BRANCH=${1:-master}  # default to master if no argument is passed

# echo "Pulling latest code from $BRANCH..."
# git fetch origin "$BRANCH"
# git checkout "$BRANCH"
# git pull origin "$BRANCH"

# # Build the Docker images
# echo "Building Docker images..."
# if ! docker-compose build; then
#     echo "Failed to build Docker images."
#     exit 1
# fi

# # Stop and remove any orphaned containers
# echo "Removing orphaned containers..."
# if ! docker-compose down --remove-orphans; then
#     echo "Failed to remove orphaned containers."
#     exit 1
# fi

# # Start the services in detached mode
# echo "Starting services in detached mode..."
# if ! docker-compose up -d; then
#     echo "Failed to start services."
#     exit 1
# fi

# echo "Waiting for Django staticfiles to be collected by container..."
# for i in {1..30}; do
#     if [ -d "./staticfiles/admin" ]; then
#         echo "Static files found!"
#         break
#     fi
#     echo "⏳ Waiting for staticfiles... ($i/30)"
#     sleep 3
# done

# # If staticfiles still not found, exit with error
# if [ ! -d "./staticfiles/admin" ]; then
#     echo "Static files were not collected in time. Aborting sync to Nginx."
#     exit 1
# fi

# # Sync static files to Nginx path
# echo "Syncing static files to Nginx..."
# rm -rf /var/www/2geda/staticfiles
# cp -r ./staticfiles /var/www/2geda/staticfiles
# chmod -R o+r /var/www/2geda/staticfiles
# find /var/www/2geda/staticfiles -type d -exec chmod o+x {} \;

# # Reload Nginx
# echo "Reloading Nginx..."
# if nginx -t && systemctl reload nginx; then
#     echo "Nginx reloaded successfully."
# else
#     echo "Nginx reload failed."
#     exit 1
# fi

# echo "🚀 Services started successfully."