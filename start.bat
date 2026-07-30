@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title iHRP Function List Tracker V3

REM ==== Cau hinh ====
set PORT=5000
set VENV_DIR=venv
set APP_URL=http://localhost:%PORT%

cd /d "%~dp0"

echo.
echo ============================================================
echo   iHRP Function List Tracker V3
echo   Port: %PORT%  ^|  URL: %APP_URL%
echo ============================================================
echo.

REM ==== 1. Kiem tra Python ====
python --version >nul 2>&1
if errorlevel 1 (
    echo [LOI] Khong tim thay Python. Cai Python 3.10+ tu python.org
    echo       Nho tich "Add Python to PATH" khi cai dat.
    pause
    exit /b 1
)

REM ==== 2. Kill process dang chiem port %PORT% VA python cu cua chinh project nay ====
echo [1/4] Don process cu...
set KILLED=0
set PIDS_TO_KILL=

REM 2a. Tim PID dang lang nghe port %PORT% (LISTENING + ESTABLISHED)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%PORT% " 2^>nul') do (
    if not "%%p"=="0" (
        echo !PIDS_TO_KILL! | findstr /C:" %%p " >nul
        if errorlevel 1 (
            set PIDS_TO_KILL=!PIDS_TO_KILL! %%p 
        )
    )
)

REM 2b. Tim python.exe dang chay app.py CUA project nay (khong dung project khac)
REM     So sanh CommandLine chua duong dan thu muc start.bat (%~dp0 co dau \ cuoi)
REM     PowerShell -Command chay ngan neu system chua co, se bo qua an toan.
set SELF_DIR=%~dp0
for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "try { Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -and $_.CommandLine -like '*%SELF_DIR%app.py*' } | Select-Object -ExpandProperty ProcessId } catch {}" 2^>nul`) do (
    echo !PIDS_TO_KILL! | findstr /C:" %%p " >nul
    if errorlevel 1 (
        set PIDS_TO_KILL=!PIDS_TO_KILL! %%p 
    )
)

if not "!PIDS_TO_KILL!"=="" (
    for %%i in (!PIDS_TO_KILL!) do (
        echo    Killing PID %%i ^(port %PORT% hoac app.py cu^)...
        taskkill /PID %%i /F /T >nul 2>&1
        if errorlevel 1 (
            echo    [WARN] Khong kill duoc PID %%i.
            echo           Neu la service he thong, thu chay start.bat voi quyen Administrator.
        ) else (
            set /a KILLED+=1
        )
    )
    if !KILLED! GTR 0 (
        echo    [OK] Da don !KILLED! process cu.
        timeout /t 2 /nobreak >nul
    )
) else (
    echo    [OK] Khong co process cu cua project nay.
)

REM ==== 3. Setup virtual environment ====
if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo [2/4] Tao virtual environment ^(lan dau^)...
    python -m venv %VENV_DIR%
    if errorlevel 1 (
        echo [LOI] Khong tao duoc venv. Kiem tra quyen thu muc.
        pause
        exit /b 1
    )
) else (
    echo [2/4] Virtual environment da san sang.
)

call "%VENV_DIR%\Scripts\activate.bat"

REM ==== 4. Cai dependencies (prod only ? pytest n?m ? requirements-dev.txt) ====
echo [3/4] Kiem tra dependencies...
python -c "import flask, openpyxl" 2>nul
if errorlevel 1 goto :INSTALL_DEPS
echo    [OK] Dependencies da san sang.
goto :DEPS_DONE

:INSTALL_DEPS
echo    Lan dau chay: dang tai flask + openpyxl ^(nhe, khong pandas^)...
echo    Ban co the theo doi tien trinh ben duoi. Thoi gian: ~30-90s tuy mang.
echo    ------------------------------------------------------------
python -m pip install --disable-pip-version-check --progress-bar on -r requirements.txt
if errorlevel 1 (
    echo [LOI] Cai dependencies that bai. Kiem tra ket noi mang.
    echo       Hoac chay: venv\Scripts\python -m pip install -r requirements.txt
    pause
    exit /b 1
)
echo    ------------------------------------------------------------
echo    [OK] Da cai xong.

:DEPS_DONE

if not exist "uploads" mkdir uploads
if not exist "uploads\projects" mkdir uploads\projects

REM ==== 5. Mo browser va khoi dong server ====
echo [4/4] Khoi dong server...
echo.
echo ============================================================
echo   Server: %APP_URL%

REM T34 Task 2 — Auto-detect LAN IP de dong nghiep cung LAN co the truy cap.
REM Loc IPv4 dau tien (bo IPv6). Neu tim thay -> in cong khai URL LAN.
REM Neu user muon private mode (chi localhost) -> set IHRP_BIND_LOCAL_ONLY=1
REM va sua host="0.0.0.0" trong app.py thanh host="127.0.0.1".
if not defined IHRP_BIND_LOCAL_ONLY (
    for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /R "IPv4"') do (
        for /f "tokens=* delims= " %%b in ("%%a") do (
            if not defined LAN_IP set LAN_IP=%%b
        )
    )
    if defined LAN_IP (
        echo   LAN URL: http://!LAN_IP!:%PORT%  ^(dong nghiep cung LAN dung URL nay^)
        echo   ADMIN MUTATIONS ^(upload, config^) chi mo tu http://localhost:%PORT%
    )
) else (
    echo   LOCAL-ONLY mode ^(IHRP_BIND_LOCAL_ONLY=1^) — LAN khong truy cap duoc.
)

echo   Nhan Ctrl+C de dung server
echo ============================================================
echo.

REM Mo browser sau 3s (chay ngam, khong block)
start "" /min cmd /c "timeout /t 3 /nobreak >nul && start %APP_URL%"

REM Chay Flask (foreground)
set PYTHONIOENCODING=utf-8
python app.py
set FLASK_EXIT=%ERRORLEVEL%

echo.
if %FLASK_EXIT% NEQ 0 (
    echo ============================================================
    echo   [LOI] Server thoat voi ma loi %FLASK_EXIT%
    echo   Doc log phia tren de xem chi tiet.
    echo ============================================================
) else (
    echo Server da dung binh thuong.
)
echo.
echo Nhan phim bat ky de dong cua so...
pause >nul
