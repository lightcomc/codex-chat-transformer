@echo off
chcp 65001 >nul 2>&1
title Codex Chat Transformer

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo Python not found. Install: https://www.python.org/downloads/
    pause
    exit /b 1
)

python "%~dp0codex_manager_gui.py" %*
if %errorlevel% neq 0 (
    echo.
    echo Error occurred. Press any key to close.
    pause >nul
)
