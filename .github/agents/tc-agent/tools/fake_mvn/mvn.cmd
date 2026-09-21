@echo off
rem Windows shim for the fake mvn used by tc_test_check_scripts.py (DEV TOOL).
python "%~dp0mvn" %*
