#!/bin/bash
# ================================================================
# PO Review System - Mac/Linux Startup Script
# ================================================================
# This script will:
# 1. Check if Python is installed
# 2. Install required dependencies
# 3. Start the FastAPI server on port 8001
# ================================================================
# 
# USAGE:
#   First time: chmod +x run_server_mac_linux.sh
#   Then run: ./run_server_mac_linux.sh
# ================================================================

echo ""
echo "========================================"
echo " PO Review System - Server Startup"
echo "========================================"
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo "[ERROR] Python is not installed!"
    echo ""
    echo "Please install Python 3.9 or higher:"
    echo "  - Mac: brew install python3"
    echo "  - Ubuntu/Debian: sudo apt install python3 python3-pip"
    echo "  - Fedora/RHEL: sudo dnf install python3 python3-pip"
    echo ""
    read -p "Press Enter to exit..."
    exit 1
fi

# Determine which python command to use
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
    PIP_CMD="pip3"
else
    PYTHON_CMD="python"
    PIP_CMD="pip"
fi

echo "[OK] Python is installed:"
$PYTHON_CMD --version
echo ""

# Check if serviceAccountKey.json exists
if [ ! -f "serviceAccountKey.json" ]; then
    echo "[WARNING] Firebase key file not found!"
    echo ""
    echo "Please place 'serviceAccountKey.json' in the project root directory."
    echo "The server may not work properly without it."
    echo ""
    echo "Expected location: $(pwd)/serviceAccountKey.json"
    echo ""
    read -p "Press Enter to continue anyway..."
fi

# Install dependencies
echo "========================================"
echo " Installing dependencies..."
echo "========================================"
echo ""
$PIP_CMD install -r requirements.txt
if [ $? -ne 0 ]; then
    echo ""
    echo "[ERROR] Failed to install dependencies!"
    echo ""
    read -p "Press Enter to exit..."
    exit 1
fi

echo ""
echo "[OK] Dependencies installed successfully!"
echo ""

# Start the server
echo "========================================"
echo " Starting FastAPI Server..."
echo "========================================"
echo ""

# Check if backend directory exists
if [ ! -d "backend" ]; then
    echo "[ERROR] Backend directory not found!"
    echo ""
    echo "Please make sure you're running this script from the project root directory."
    echo "Expected structure: project_root/backend/main.py"
    echo ""
    read -p "Press Enter to exit..."
    exit 1
fi

echo "Server will start on: http://localhost:8001"
echo ""
echo "Press Ctrl+C to stop the server."
echo ""

cd backend
$PYTHON_CMD main.py

# If server stops, show message and wait
echo ""
echo "========================================"
echo " Server stopped"
echo "========================================"
echo ""
read -p "Press Enter to exit..."
