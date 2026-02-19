# HReader Android App

A simple WebView wrapper for the HReader book server. No browser required on your phone.

## Building

1. Open this folder (`android-app`) in Android Studio
2. Let Gradle sync
3. Build > Build APK or Run on connected device

## Usage

1. Start the server on your laptop:
   ```bash
   cd /path/to/hreader
   uv run python server.py
   ```

2. Open the app on your phone

3. Enter your laptop's IP address (e.g., `192.168.1.100`)
   - The app will add `:8123` automatically
   - Find your IP with `ip addr` (Linux) or `ipconfig` (Windows)

4. Tap Connect

The app remembers your server address for next time.
