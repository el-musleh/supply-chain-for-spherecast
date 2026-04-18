#!/bin/bash

# setup.sh - Environment setup for Hackathon 2026 (Spherecast Agnes Prototype)

echo "Setting up Hackathon 2026 Environment..."

# Ensure python3 is available
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 could not be found. Please install Python 3 first."
    exit 1
fi

# Ensure pipx is installed
if ! command -v pipx &> /dev/null; then
    echo "Error: pipx could not be found."
    echo "Please install pipx first:"
    echo "  Ubuntu/Debian: sudo apt install pipx"
    echo "  macOS: brew install pipx"
    exit 1
fi

# Ensure pipx-managed binaries (e.g. jupyter-lab) are on PATH
pipx ensurepath

# Remove the conflicting legacy package if present — it breaks 'from google import genai'
if python3 -c "import google.generativeai" &> /dev/null; then
    echo "Removing conflicting 'google-generativeai' package..."
    pip uninstall google-generativeai -y --break-system-packages 2>/dev/null || true
fi

echo "Installing Jupyter and required packages via pipx..."
# Install jupyter and jupyterlab globally in isolated environments
pipx install jupyterlab --force
pipx install jupyter --include-deps --force

# Inject the necessary data science and AI libraries
echo "Injecting data science libraries and Gemini API..."
pipx inject jupyterlab pandas matplotlib sqlite3-api google-genai ipywidgets
pipx inject jupyter pandas matplotlib sqlite3-api google-genai ipywidgets

# Install web scraping dependencies
echo "Installing web scraping dependencies..."
pipx inject jupyterlab playwright beautifulsoup4 requests pymupdf Pillow
pipx inject jupyter playwright beautifulsoup4 requests pymupdf Pillow

# Install Playwright browsers
echo "Installing Playwright browsers ( Chromium )..."
python3 -m playwright install chromium

echo ""
echo "Downloading ML models for offline RAG..."
python3 download_models.py || echo "  (download_models.py not found, skipping)"

# Remind contributor to set their API key
echo ""
if [ -z "$GEMINI_API_KEY" ]; then
    echo "⚠️  GEMINI_API_KEY is not set in your environment."
    echo "   Add this to your ~/.bashrc or ~/.zshrc:"
    echo "   export GEMINI_API_KEY='your-key-here'"
    echo "   Then run: source ~/.bashrc"
else
    echo "✓ GEMINI_API_KEY is already set."
fi

echo ""
echo "==========================================="
echo "Environment setup complete!"
echo "To start working, simply run: jupyter-lab"
echo "NOTE: Open a new terminal first if 'jupyter-lab'"
echo "      is not found (pipx ensurepath needs a reload)."
echo "==========================================="
