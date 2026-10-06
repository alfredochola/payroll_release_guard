@echo off
cd /d "%~dp0"
title Payroll Release Guard - leave this window open during the demo
python -m streamlit run app.py --server.port 8502
