# run.py
# Script to launch the GRIDLOCK AI Command Center and open the web dashboard automatically.

import subprocess
import time
import webbrowser
import sys
import os

def main():
    print("[GRIDLOCK Start] Launching FastAPI backend server (dashboard_api.py)...")
    
    # Run dashboard_api.py in a separate process
    cmd = [sys.executable, "dashboard_api.py"]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    
    # Give the server a moment to start up and bind to port 5000
    time.sleep(2.0)
    
    url = "http://localhost:5000"
    print(f"[GRIDLOCK Start] Opening dashboard automatically at: {url}")
    webbrowser.open(url)
    
    print("[GRIDLOCK Start] Server is running. Press Ctrl+C to terminate.")
    
    try:
        # Keep process running and stream output
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                sys.stdout.write(line)
                sys.stdout.flush()
    except KeyboardInterrupt:
        print("\n[GRIDLOCK Start] Shutting down server...")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        print("[GRIDLOCK Start] Server terminated.")

if __name__ == "__main__":
    main()
