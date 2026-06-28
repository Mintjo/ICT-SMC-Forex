@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0\.."

echo === ICT-SMC-Forex : setup Windows + MT5 reel ===
echo.

echo [1/7] Verification de Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo ECHEC : Python n'est pas installe ou pas dans le PATH.
    echo Installez Python 3.10+ depuis https://www.python.org/downloads/ puis relancez ce script.
    exit /b 1
)
python --version
echo OK
echo.

echo [2/7] Installation des dependances (requirements.txt)...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo ECHEC : installation des dependances.
    exit /b 1
)
echo OK
echo.

echo [3/7] Verification du package MetaTrader5...
python -c "import MetaTrader5" >nul 2>&1
if errorlevel 1 (
    echo ECHEC : le package MetaTrader5 n'est pas installe.
    echo Verifiez qu'il est present dans requirements.txt et reessayez.
    exit /b 1
)
echo OK
echo.

echo [4/7] Test de connexion MT5...
echo Assurez-vous que le terminal MT5 est ouvert et connecte, et que
echo MT5_LOGIN / MT5_PASSWORD / MT5_SERVER sont definis (.env ou variables d'environnement).
python data\test_mt5_connection.py
if errorlevel 1 (
    echo ECHEC : connexion MT5 impossible. Verifiez vos identifiants et que le terminal est lance.
    exit /b 1
)
echo OK
echo.

echo [5/7] Telechargement de 30 jours de donnees EUR/USD M5 reelles...
python data\download_real_data.py --symbol EURUSD --days 30
if errorlevel 1 (
    echo ECHEC : telechargement des donnees reelles.
    exit /b 1
)
echo OK
echo.

echo [6/7] Lancement du backtest en mode STRICT sur les donnees reelles...
python backtest\silver_bullet_backtest.py --mode strict --data data\historical\EURUSD_M5_real.csv
if errorlevel 1 (
    echo ECHEC : le backtest a echoue.
    exit /b 1
)
echo OK
echo.

echo [7/7] Rapport genere dans results\backtest_report.html et results\trades_log.csv
echo.
echo === Setup termine avec succes ===
endlocal
