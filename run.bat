@echo off
cd /d "%~dp0"
REM Set this path if Blender is not detected automatically:
REM set "BLENDER=C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
py -3 -m pip install -r requirements.txt || goto :error
py -3 server.py
exit /b
:error
pause
