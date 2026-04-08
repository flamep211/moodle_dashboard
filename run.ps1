#!/bin/bash
# PowerShell script to run the Flask app

cd "$PSScriptRoot"

# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Run the app
python run.py
