@echo off
rem APSVN. Запускається власним Python із теки runtime, тому на компʼютері
rem художника нічого встановлювати не треба. Системний Python — лише запасний
rem варіант для розробки.
setlocal
set "APP=%~dp0app.py"

if exist "%~dp0runtime\pythonw.exe" (
  start "" "%~dp0runtime\pythonw.exe" "%APP%"
  goto :eof
)

where pythonw >nul 2>&1
if %errorlevel%==0 (
  start "" pythonw "%APP%"
  goto :eof
)

echo.
echo   APSVN cannot start.
echo.
echo   There must be a "runtime" folder next to this file - that is where
echo   the Python it needs lives. Most likely APSVN was copied only in
echo   part: copy the whole APSVN folder and try again.
echo.
pause
