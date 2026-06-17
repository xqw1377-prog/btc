#!/bin/bash

set -e

echo "Starting AURORA Production Engine..."

if [ -f .env ]; then
    echo "Loading environment from .env"
    export $(cat .env | grep -v '^#' | xargs)
fi

if [ "$1" == "docker" ]; then
    echo "Starting with Docker..."
    docker-compose up -d
    echo "AURORA started in Docker containers"
    echo "Monitoring: http://localhost:3000"
elif [ "$1" == "testnet" ]; then
    echo "Starting in testnet mode..."
    python -m aurora.production_main
elif [ "$1" == "live" ]; then
    echo "Starting in LIVE mode..."
    read -p "Are you sure you want to start LIVE trading? (yes/no): " confirm
    if [ "$confirm" == "yes" ]; then
        python -m aurora.production_main
    else
        echo "Aborted"
    fi
else
    echo "Usage: ./start.sh [docker|testnet|live]"
    echo ""
    echo "Options:"
    echo "  docker   - Start with Docker (includes Redis and monitoring)"
    echo "  testnet  - Start in Binance testnet mode"
    echo "  live     - Start in LIVE trading mode (real money)"
fi