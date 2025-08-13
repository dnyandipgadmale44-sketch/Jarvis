JarvisPC — Local Voice Assistant
=================================
This is a minimal local assistant that listens when you hold SPACE,
uses OpenAI for transcription + intent matching, and opens apps/folders/files.

Quick start (Windows):
1) Install Python 3.10+
2) In PowerShell:
   cd <where you unzipped>/JarvisPC
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
3) Copy .env.example to .env and paste your OpenAI API key
4) Edit actions.yaml to point to your real paths
5) Run: python main.py
   Hold SPACE and say things like "open downloads", "open Photoshop".

Troubleshooting:
- If PyAudio fails on Windows, install it via a prebuilt wheel or pipwin:
  pip install pipwin && pipwin install pyaudio
- If mic isn't found, ensure your default input device is enabled.
- To auto-start on login, create a shortcut to run_jarvis.bat inside shell:startup
