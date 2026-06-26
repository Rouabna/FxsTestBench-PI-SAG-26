@echo off
REM ===========================================================================
REM  Version PORTABLE de run_gateway_server.bat (pour un AUTRE PC, ex. collegue)
REM  ---------------------------------------------------------------------------
REM  Aucune chemin en dur : se lance depuis SON PROPRE dossier (%~dp0) et utilise
REM  le Python du PATH. A placer DANS LE MEME DOSSIER que gateway_server.py.
REM
REM  Pre-requis sur ce PC :
REM    1) Python installe avec l'option "Add Python to PATH" cochee.
REM    2) Flask installe :  pip install flask
REM    3) gateway_server.py + gateway_voice.py presents a cote de ce .bat.
REM    4) Le PC doit joindre le gateway :  ping 192.168.5.1  doit repondre.
REM
REM  Demarrage auto : Win+R -> shell:startup -> y placer un raccourci vers ce .bat.
REM ===========================================================================
cd /d "%~dp0"
python gateway_server.py
pause
