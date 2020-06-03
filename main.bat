@echo off
set LOGURU_LEVEL=INFO
cmd /k %cd%\.python\python %cd%\main.py "%~1"