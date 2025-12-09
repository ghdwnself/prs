@echo off
REM ================================================================
REM PO Review System - Windows Startup Script
REM ================================================================
REM This script will:
REM 1. Check if Python is installed
REM 2. Install required dependencies
REM 3. Start the FastAPI server on port 8001
REM ================================================================

echo.
echo ========================================
echo  PO Review System - Server Startup
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH!
    echo.
    echo Please install Python 3.9 or higher from:
    echo https://www.python.org/downloads/
    echo.
    echo *** IMPORTANT: Check "Add Python to PATH" during installation! ***
    echo.
    pause
    exit /b 1
)

echo [OK] Python is installed:
python --version
echo.

REM Check if serviceAccountKey.json exists
if not exist "serviceAccountKey.json" (
    echo [WARNING] Firebase key file not found!
    echo.
    echo Please place 'serviceAccountKey.json' in the project root directory.
    echo The server may not work properly without it.
    echo.
    echo Expected location: %CD%\serviceAccountKey.json
    echo.
    pause
)

REM Install dependencies
echo ========================================
echo  Installing dependencies...
echo ========================================
echo.
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to install dependencies!
    echo.
    pause
    exit /b 1
)

echo.
echo [OK] Dependencies installed successfully!
echo.

REM Start the server
echo ========================================
echo  Starting FastAPI Server...
echo ========================================
echo.

REM Check if backend directory exists
if not exist "backend" (
    echo [ERROR] Backend directory not found!
    echo.
    echo Please make sure you're running this script from the project root directory.
    echo Expected structure: project_root\backend\main.py
    echo.
    pause
    exit /b 1
)

echo Server will start on: http://localhost:8001
echo.
echo Press Ctrl+C to stop the server.
echo.

cd backend
python main.py

REM If server stops, show message and wait
echo.
echo ========================================
echo  Server stopped
echo ========================================
echo.
pause
