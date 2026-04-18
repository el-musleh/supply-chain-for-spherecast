#!/bin/bash

# setup.sh - Environment setup for Hackathon 2026 (Spherecast Agnes Prototype)

echo "Setting up Hackathon 2026 Environment..."

# Ensure pipx is installed
if ! command -v pipx &> /dev/null; then
    echo "Error: pipx could not be found."
    echo "Please install pipx first:"
    echo "  Ubuntu/Debian: sudo apt install pipx"
    echo "  macOS: brew install pipx"
    exit 1
fi

echo "Installing Jupyter and required packages via pipx..."
# Install jupyter and jupyterlab globally in isolated environments
pipx install jupyterlab --force
pipx install jupyter --include-deps --force

# Inject the necessary data science and AI libraries
echo "Injecting data science libraries and Gemini API..."
pipx inject jupyterlab pandas matplotlib sqlite3-api google-genai ipywidgets
pipx inject jupyter pandas matplotlib sqlite3-api google-genai ipywidgets

echo "==========================================="
echo "Environment setup complete!"
echo "To start working, simply run: jupyter-lab"
echo "==========================================="
