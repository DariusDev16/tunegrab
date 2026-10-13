@echo off
REM TuneGrab - Spotify playlist -> YouTube -> mp3
REM Mantido em ASCII puro de proposito: .bat com acento quebra conforme o
REM code page do console e imprime lixo em vez da mensagem.

title TuneGrab
chcp 65001 >nul
setlocal

set "PY="
where py >nul 2>&1 && set "PY=py"
if not defined PY (
  for %%P in (
    "%LOCALAPPDATA%\Python\bin\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
  ) do (
    if exist %%P if not defined PY set "PY=%%~P"
  )
)
if not defined PY (
  echo.
  echo   [ERRO] Python nao encontrado.
  echo.
  echo   Instale o Python 3 em https://www.python.org
  echo   e marque "Add Python to PATH" na instalacao.
  echo.
  pause
  exit /b 1
)

REM Com argumentos: modo terminal, sem pause (nao atrapalha quem usa em script).
if not "%~1"=="" (
  "%PY%" "%~dp0tunegrab.py" %*
  exit /b %ERRORLEVEL%
)

REM Sem argumentos: duplo-clique. O Python pergunta o link e o pause segura
REM a janela aberta no fim. (Nao usar "set /p" aqui: engole espaco/CR.)
"%PY%" "%~dp0tunegrab.py"
set "RC=%ERRORLEVEL%"
echo.
echo   Finished ^(exit code %RC%^)
pause
exit /b %RC%