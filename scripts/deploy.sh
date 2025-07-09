#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

REPO_NAME="<your-dockerhub-username>/chat-server" # Replace with your Docker Hub username
TAG="latest" # Or a version tag passed by CI/CD

echo "Pulling latest Docker image: ${REPO_NAME}:${TAG}"
docker pull "${REPO_NAME}:${TAG}"

echo "Stopping existing services..."
docker-compose down || true # --volumes can be added to remove volumes, but we want to persist data

echo "Starting new services..."
docker-compose up -d --no-build # --no-build ensures we use the pulled image, not rebuild

echo "Deployment complete."
