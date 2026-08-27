#!/bin/sh
set -e

# Export the database password for psql commands
export PGPASSWORD=$POSTGRES_PASSWORD
POSTGRES_HOST=${POSTGRES_HOST:-db}  
POSTGRES_PORT=${POSTGRES_PORT:-5432}
POSTGRES_USER=${POSTGRES_USER:-postgres}

# Wait for PostgreSQL to be ready (Explicitly using -d postgres)
echo "Waiting for PostgreSQL to be ready..."
until pg_isready -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d postgres; do
  echo "Waiting for database connection..."
  sleep 2
done

# Check if the database exists (Explicitly using -d postgres)
echo "Checking if the database exists..."
psql -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d postgres -c "SELECT 1 FROM pg_database WHERE datname='$POSTGRES_DB'" | grep -q 1 || {
  echo "Database does not exist. Creating database..."
  psql -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE $POSTGRES_DB"
}

# Run migrations
# echo "Running makemigrations..."
# python manage.py makemigrations


# Run migrations
echo "Running migrations..."
python manage.py migrate --noinput

# Run to sync config variables
echo "Running sync of variables to DB"
python manage.py sync_config

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput

# Start the server
echo "Starting server..."
exec "$@"