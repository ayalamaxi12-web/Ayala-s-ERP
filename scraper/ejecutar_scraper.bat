@echo off
REM Corrida diaria del scraper de competencia. La programa la Tarea de Windows (ver README_WINDOWS.md).
REM Pasar argumentos extra si hace falta, por ejemplo:  ejecutar_scraper.bat --vendedor tecnovibe
cd /d "%~dp0"
python scraper.py %*
set CODIGO=%ERRORLEVEL%
echo Terminó con código %CODIGO% (0=ok, 1=error, 2=ML pidió login/verificación). Ver carpeta logs\
exit /b %CODIGO%
