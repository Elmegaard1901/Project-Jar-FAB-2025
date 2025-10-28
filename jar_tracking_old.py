import serial
import time
import json
import threading
from datetime import datetime
from flask import Flask, Response, render_template_string

# --- Configuration ---
SERIAL_PORT = "/dev/cu.usbmodem1101"  # Adjust for your setup (e.g., COM3 on Windows)
BAUD_RATE = 115200

app = Flask(__name__)

# --- Global state ---
arduino = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
latest_data = {"dist1": None, "state1": None, "dist2": None, "state2": None}
event_log = []  # stores {"time", "row", "event", "distance"}

# --- SERIAL READER THREAD ---
def read_serial():
    prev_state1, prev_state2 = None, None
    while True:
        try:
            line = arduino.readline().decode("utf-8").strip()
            if not line or line.startswith("Dist1"):
                continue

            parts = line.split(",")
            if len(parts) == 6:
                dist1, state1, dist2, state2 = float(parts[0]), int(parts[1]), float(parts[2]), int(parts[3])
                latest_data.update({
                    "dist1": dist1, "state1": state1,
                    "dist2": dist2, "state2": state2
                })

                # --- Detect state change for Row 1 ---
                if prev_state1 is not None and prev_state1 != state1:
                    event_log.append({
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "row": 1,
                        "event": "Change detected",
                        "distance": round(dist1, 1)
                    })

                # --- Detect state change for Row 2 ---
                if prev_state2 is not None and prev_state2 != state2:
                    event_log.append({
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "row": 2,
                        "event": "Change detected",
                        "distance": round(dist2, 1)
                    })

                prev_state1, prev_state2 = state1, state2
            time.sleep(0.1)
        except Exception as e:
            print("Error:", e)
            time.sleep(1)

threading.Thread(target=read_serial, daemon=True).start()

# --- SSE (Server-Sent Events) for Live Updates ---
@app.route("/events")
def events():
    def stream():
        last_data = {}
        while True:
            if latest_data != last_data:
                yield f"data: {json.dumps(latest_data)}\n\n"
                last_data = latest_data.copy()
            time.sleep(0.2)
    return Response(stream(), mimetype="text/event-stream")

# --- REST endpoint to get recent logs ---
@app.route("/log")
def get_log():
    return {"events": event_log[-50:]}  # Last 50 entries

# --- Web Interface ---
@app.route("/")
def index():
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Jar Movement Monitor</title>
        <style>
            body { font-family: sans-serif; background: #f4f4f4; text-align: center; }
            .container { display: flex; justify-content: center; flex-wrap: wrap; }
            .card { margin: 15px; padding: 20px; background: white; border-radius: 10px; width: 200px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); }
            .alert { color: red; font-weight: bold; }
            .ok { color: green; }
            table { margin: 20px auto; border-collapse: collapse; width: 80%; background: white; }
            th, td { border: 1px solid #ccc; padding: 8px; }
            th { background: #eee; }
        </style>
    </head>
    <body>
        <h1>Jar Movement Monitor</h1>
        <div class="container">
            <div class="card">
                <h2>Row 1</h2>
                <div id="row1">Waiting for data...</div>
            </div>
            <div class="card">
                <h2>Row 2</h2>
                <div id="row2">Waiting for data...</div>
            </div>
        </div>

        <h2>Change Log</h2>
        <table id="logTable">
            <thead><tr><th>Time</th><th>Row</th><th>Event</th><th>Distance (cm)</th></tr></thead>
            <tbody></tbody>
        </table>

        <script>
            const evtSource = new EventSource("/events");
            evtSource.onmessage = function(e) {
                const data = JSON.parse(e.data);

                // Update Row 1
                document.getElementById("row1").innerHTML =
                    data.state1 !== null
                        ? (data.state1
                            ? "<span class='alert'>Change detected in Row 1</span>"
                            : "<span class='ok'>No change</span>")
                        : "Waiting...";

                // Update Row 2
                document.getElementById("row2").innerHTML =
                    data.state2 !== null
                        ? (data.state2
                            ? "<span class='alert'>Change detected in Row 2</span>"
                            : "<span class='ok'>No change</span>")
                        : "Waiting...";
            };

            async function updateLog() {
                const res = await fetch("/log");
                const json = await res.json();
                const tbody = document.querySelector("#logTable tbody");
                tbody.innerHTML = "";
                json.events.slice().reverse().forEach(e => {
                    const row = `<tr>
                        <td>${e.time}</td>
                        <td>${e.row}</td>
                        <td>${e.event}</td>
                        <td>${e.distance}</td>
                    </tr>`;
                    tbody.innerHTML += row;
                });
            }
            setInterval(updateLog, 2000);
            updateLog();
        </script>
    </body>
    </html>
    """
    return render_template_string(html)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
