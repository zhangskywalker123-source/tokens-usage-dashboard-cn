@echo off
setlocal
set "DIR=%~dp0"
set "STAGE=%DIR%exe-build\stage"
set "NODE=node"
if defined TOKEN_DASH_NODE_EXE set "NODE=%TOKEN_DASH_NODE_EXE%"
set "CLI=%STAGE%\node_modules\codeburn\dist\cli.js"

if not exist "%CLI%" (
  echo Installing locked CodeBurn dependencies...
  call npm ci --prefix "%STAGE%"
  if errorlevel 1 goto failed
)

set "NODE_PATH=%STAGE%\node_modules"
"%NODE%" "%CLI%" export --format json -o "%DIR%usage.json"
if errorlevel 1 goto failed
"%NODE%" "%DIR%build.js"
if errorlevel 1 goto failed
echo Dashboard updated.
goto done

:failed
echo Refresh failed. Check that Node.js 22 and npm are installed.

:done
pause
endlocal
