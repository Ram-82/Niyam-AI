@echo off
setlocal
cd /d "%~dp0"

echo [INFO] Checking Niyam AI Backend Setup...

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.10+ from python.org and try again.
    pause
    exit /b 1
)

:: Navigate to backend
if exist "niyam-backend" (
    cd niyam-backend
) else (
    echo [ERROR] niyam-backend directory not found!
    pause
    exit /b 1
)

:: Create Virtual Env if missing
if not exist "venv" (
    echo [INFO] Creating virtual environment...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

:: Activate
call venv\Scripts\activate

:: Install Dependencies
echo [INFO] Installing/Updating dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies.
    echo Please check your internet connection and try again.
    pause
    exit /b 1
)

:: Start Server
echo [INFO] Starting Server...
echo [INFO] API will be available at https://niyam-ai-beryl.vercel.app/
echo [INFO] Press Ctrl+C to stop.
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001

if %errorlevel% neq 0 (
    echo [ERROR] Server crashed. Check the error message above.
    pause
)
