@echo off
set LOGURU_LEVEL=INFO
cmd /k %~dp0\.python\python %~dp0\main.py "%~1"