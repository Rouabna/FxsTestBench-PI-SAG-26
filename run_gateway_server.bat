@echo off
REM Lance le serveur gateway PC (gateway_server.py) avec le bon interpreteur Python.
REM Double-cliquer pour demarrer, ou placer un raccourci dans le dossier Demarrage
REM de Windows (Win+R -> shell:startup) pour un lancement automatique a l'ouverture.
cd /d "D:\ing-pfe-bancTest\deploy_test_final"
"C:\Python313\python.exe" gateway_server.py
pause
