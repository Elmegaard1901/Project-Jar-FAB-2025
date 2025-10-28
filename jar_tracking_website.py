import io
import PIL
import qrcode
import serial
import time
import json
import threading
from datetime import datetime
from flask import Flask, Response, render_template_string, request, jsonify, send_file, url_for

# --- Configuration ---
SERIAL_PORT = "/dev/cu.usbmodem1101"  # Adjust (e.g. "COM3" on Windows)
BAUD_RATE = 115200
MOCK_MODE = False  # Set to True to run without serial device

app = Flask(__name__)

# --- Global state ---
try:
    arduino = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    print("Connected to Arduino")
except serial.SerialException:
    print("Warning: Could not connect to Arduino. Running in mock mode.")
    arduino = None
    MOCK_MODE = True

latest_data = {"dist1": None, "state1": None, "dist2": None, "state2": None, "lower": 30.0, "upper": 40.0}
event_log = []  # stores {"time", "row", "event", "distance"}
alerts = {1: False, 2: False}  # Which rows need checking
misplaced_jars = []  # List of {"jar": "R0244", "found_in": 2}

# Define jars per row
row_jars = {
    1: ["H004040", "H004041"],
    2: ["R0244", "R0245", "R0246", "R0247", "R47376", "R47346", "R47347"],
}

# --- SERIAL READER THREAD ---
def read_serial():
    prev_state1, prev_state2 = None, None
    mock_counter = 0
    mock_state1, mock_state2 = 0, 0  # Track mock states separately
    while True:
        try:
            if MOCK_MODE or arduino is None:
                import random
                time.sleep(1)
                # Use the same threshold values as Arduino
                lower_threshold = 30.0
                upper_threshold = 40.0
                
                mock_counter += 1
                
                # Simulate realistic scenario: mostly normal distances, occasional jar placement/removal
                if mock_counter % 20 == 0:  # Every 20 seconds, potential state change
                    # 30% chance of triggering an event for each sensor
                    if random.random() < 0.3:
                        mock_state1 = 1 - mock_state1  # Toggle state
                    if random.random() < 0.3:
                        mock_state2 = 1 - mock_state2  # Toggle state
                
                # Set distances based on current states (simulate Arduino behavior)
                if mock_state1 == 1:
                    # "Needs checking" state - distance below lower threshold
                    dist1 = lower_threshold - random.uniform(1, 8)
                else:
                    # Normal state - distance above upper threshold
                    dist1 = upper_threshold + random.uniform(5, 20)
                    
                if mock_state2 == 1:
                    # "Needs checking" state - distance below lower threshold  
                    dist2 = lower_threshold - random.uniform(1, 8)
                else:
                    # Normal state - distance above upper threshold
                    dist2 = upper_threshold + random.uniform(5, 20)
                
                state1, state2 = mock_state1, mock_state2
            else:
                line = arduino.readline().decode("utf-8").strip()
                if not line or line.startswith("Dist1"):
                    continue
                parts = line.split(",")
                if len(parts) < 4:
                    continue
                # Arduino sends distance1,state1,distance2,state2 and optionally lower,upper thresholds
                dist1, state1, dist2, state2 = float(parts[0]), int(parts[1]), float(parts[2]), int(parts[3])
                # If Arduino also sends threshold values, use them for visualization
                lower_threshold = float(parts[4]) if len(parts) > 4 else 30.0
                upper_threshold = float(parts[5]) if len(parts) > 5 else 40.0

            latest_data.update({
                "dist1": dist1, "state1": state1,
                "dist2": dist2, "state2": state2,
                "lower": lower_threshold, "upper": upper_threshold
            })

            # Detect transitions into the "needs checking" state (distance < lower)
            # Only set alerts when the state transitions to 1. Clearing alerts is
            # still manual via the /clear_alert endpoint.
            if prev_state1 is not None and prev_state1 != state1 and state1 == 1:
                event_log.append({
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "row": 1,
                    "event": "Needs checking",
                    "distance": round(dist1, 1)
                })
                alerts[1] = True
            if prev_state2 is not None and prev_state2 != state2 and state2 == 1:
                event_log.append({
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "row": 2,
                    "event": "Needs checking",
                    "distance": round(dist2, 1)
                })
                alerts[2] = True

            prev_state1, prev_state2 = state1, state2
            if not MOCK_MODE:
                time.sleep(0.1)
        except Exception as e:
            print("Error:", e)
            time.sleep(1)

threading.Thread(target=read_serial, daemon=True).start()

# --- QR Code Generation ---
@app.route("/qr/<int:row>")
def generate_qr(row):
    """Generate a QR code for the checklist page of a given row."""
    if row not in row_jars:
        return "Invalid row", 404

    # Generate URL for this specific row
    qr_url = request.url_root.strip("/") + url_for("checklist_row", row=row)
    img = qrcode.make(qr_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

# --- SSE for Live Updates ---
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

# --- REST Endpoints ---
@app.route("/log")
def get_log():
    return {"events": event_log[-50:]}

@app.route("/alerts")
def get_alerts():
    return jsonify(alerts)

@app.route("/clear_alert/<int:row>", methods=["POST"])
def clear_alert(row):
    alerts[row] = False
    return jsonify({"success": True})

@app.route("/mark_wrong_jar", methods=["POST"])
def mark_wrong_jar():
    data = request.json
    jar = data.get("jar")
    found_in = data.get("found_in")

    if not jar or not found_in:
        return jsonify({"success": False, "error": "Missing data"}), 400

    # Find correct row for this jar
    correct_row = None
    for row, jars in row_jars.items():
        if jar in jars:
            correct_row = row
            break

    misplaced_entry = {
        "jar": jar,
        "found_in": found_in,
        "correct_row": correct_row,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    misplaced_jars.append(misplaced_entry)

    response = {
        "success": True,
        "message": f"Jar {jar} belongs in Row {correct_row}" if correct_row else "Jar not found in database.",
        "correct_row": correct_row
    }
    return jsonify(response)


# --- Pages ---
@app.route("/")
def home():
    """Home page with alerts and QR codes for each row."""
    qr_cards = "".join([
        f"""
        <div class='card'>
            <h3>Row {row}</h3>
            <img src='/qr/{row}' alt='QR for Row {row}' width='150'><br>
            <a href='/checklist/{row}' class='button'>Open Checklist</a>
        </div>
        """ for row in row_jars
    ])

    html = f"""
    <html>
    <head>
        <title>Jar Tracking System</title>
        <style>
            body {{ font-family: sans-serif; background: #f9f9f9; padding: 20px; }}
            .card {{ background: white; padding: 20px; border-radius: 8px;
                     box-shadow: 0 2px 6px rgba(0,0,0,0.1); margin: 10px; display: inline-block; text-align: center; }}
            .alert {{ color: red; font-weight: bold; }}
            .ok {{ color: green; }}
            a.button {{ display: inline-block; padding: 10px 20px; background: #007bff; color: white;
                        border-radius: 5px; text-decoration: none; margin-top: 10px; }}
        </style>
    </head>
    <body>
        <h1>Jar Tracking System</h1>
        <p>This system tracks movement of jars in monitored rows using ultrasonic sensors.</p>
        {"<div style='background: #fff3cd; padding: 10px; border-radius: 5px;'><strong>⚠️ Running in Mock Mode</strong></div>" if MOCK_MODE else ""}
        
        <h2>Current Alerts</h2>
        <div id="alerts"></div>
        <br>

        <div>{qr_cards}</div>
        <br>
        <a class="button" href="/live">View Live Tracking</a>
        <a class="button" href="/event_log">View Event Log</a>
        <a class="button" href="/misplaced">View Misplaced Jars Log</a>

        <script>
            async function loadAlerts() {{
                const res = await fetch("/alerts");
                const data = await res.json();
                let html = "";
                for (const [row, alert] of Object.entries(data)) {{
                    html += alert
                        ? `<div class='alert'>⚠️ Row ${{row}} requires checking!</div>`
                        : `<div class='ok'>✅ Row ${{row}} is OK.</div>`;
                }}
                document.getElementById("alerts").innerHTML = html;
            }}
            loadAlerts();
            setInterval(loadAlerts, 3000);
        </script>
    </body>
    </html>
    """
    return render_template_string(html)

@app.route("/live")
def live_page():
    html = """
    <html>
    <head>
        <title>Live Jar Tracking</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body { font-family: sans-serif; background: #f9f9f9; padding: 20px; }
            .card { background: white; padding: 20px; border-radius: 8px;
                    box-shadow: 0 2px 6px rgba(0,0,0,0.1); margin: 10px 0; }
            .sensor { display: inline-block; margin: 10px; padding: 15px;
                      border-radius: 5px; min-width: 120px; text-align: center; }
            .active { background: #f44336; color: white; }
            .inactive { background: #4CAF50; color: white; }
            canvas { background: white; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); margin-top: 20px; }
        </style>
    </head>
    <body>
        <h1>Live Tracking</h1>

        <div id="data"></div>
        <canvas id="chart" width="900" height="400"></canvas>
        <a href="/">⬅ Back to Home</a>

        <script>
            const ctx = document.getElementById('chart').getContext('2d');
            const maxPoints = 100;

            const chart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [
                        {
                            label: 'Distance 1 (cm)',
                            data: [],
                            borderColor: 'rgba(75,192,192,1)',
                            tension: 0.2,
                            fill: false
                        },
                        {
                            label: 'Distance 2 (cm)',
                            data: [],
                            borderColor: 'rgba(255,99,132,1)',
                            tension: 0.2,
                            fill: false
                        },
                        {
                            label: 'Lower Threshold',
                            data: [],
                            borderColor: 'rgba(255,165,0,0.6)',
                            borderDash: [5,5],
                            pointRadius: 0
                        },
                        {
                            label: 'Upper Threshold',
                            data: [],
                            borderColor: 'rgba(255,165,0,0.6)',
                            borderDash: [5,5],
                            pointRadius: 0
                        }
                    ]
                },
                options: {
                    animation: false,
                    responsive: true,
                    scales: {
                        y: { title: { display: true, text: 'Distance (cm)' }, min: 0, max: 100 },
                        x: { display: false }
                    }
                }
            });

            const eventSource = new EventSource('/events');
            eventSource.onmessage = (event) => {
                const data = JSON.parse(event.data);
                const now = new Date().toLocaleTimeString();

                // Update sensor status cards
                document.getElementById('data').innerHTML = `
                    <div class='card'>
                        <h3>Sensor Status</h3>
                        <div class='sensor ${data.state1 ? 'active' : 'inactive'}'>
                            Row 1<br>${data.dist1?.toFixed(1) || 'N/A'} cm
                        </div>
                        <div class='sensor ${data.state2 ? 'active' : 'inactive'}'>
                            Row 2<br>${data.dist2?.toFixed(1) || 'N/A'} cm
                        </div>
                    </div>
                `;

                // Push new values to chart
                chart.data.labels.push(now);
                chart.data.datasets[0].data.push(data.dist1 || 0);
                chart.data.datasets[1].data.push(data.dist2 || 0);
                chart.data.datasets[2].data.push(data.lower || 30);
                chart.data.datasets[3].data.push(data.upper || 40);

                // Keep last 100 points
                if (chart.data.labels.length > maxPoints) {
                    chart.data.labels.shift();
                    chart.data.datasets.forEach(ds => ds.data.shift());
                }

                chart.update();
            };
        </script>
    </body>
    </html>
    """
    return render_template_string(html)

@app.route("/checklist/<int:row>")
def checklist_row(row):
    if row not in row_jars:
        return "Invalid row", 404

    jars = "".join(f"<li>{jar}</li>" for jar in row_jars[row])
    html = f"""
    <html>
    <head>
        <title>Checklist - Row {row}</title>
        <style>
            body {{ font-family: sans-serif; background: #fafafa; padding: 20px; }}
            .card {{ background: white; padding: 20px; border-radius: 8px; margin: 10px 0;
                     box-shadow: 0 2px 6px rgba(0,0,0,0.1); }}
            input {{ padding: 5px; margin: 5px; }}
            button {{ padding: 5px 10px; }}
        </style>
    </head>
    <body>
        <h1>Checklist - Row {row}</h1>
        <p>Confirm which jars are in place and mark misplaced jars.</p>
        <div class='card'>
            <ul>{jars}</ul>
            <button onclick="clearAlert({row})">Clear Alert</button>
            <br><br>
            <input id="jar_{row}" placeholder="Jar ID (if misplaced)">
            <button onclick="markWrongJar({row})">Mark Wrong Jar</button>
        </div>
        <a href="/">⬅ Back to Home</a>

        <script>
        async function clearAlert(row) {{
            const res = await fetch(`/clear_alert/${{row}}`, {{
                method: "POST"
            }});
            const data = await res.json();
            
            if (data.success) {{
                alert(`Alert for Row ${{row}} has been cleared!`);
            }} else {{
                alert("Error clearing alert. Please try again.");
            }}
        }}

        async function markWrongJar(row) {{
            const jar = document.getElementById(`jar_${{row}}`).value.trim();
            if (!jar) return alert("Please enter a jar ID");

            const res = await fetch("/mark_wrong_jar", {{
                method: "POST",
                headers: {{ "Content-Type": "application/json" }},
                body: JSON.stringify({{ jar, found_in: row }})
            }});
            const data = await res.json();

            if (data.success) {{
                if (data.correct_row && data.correct_row !== row) {{
                    alert(`Jar ${{jar}} belongs in Row ${{data.correct_row}}. Please move it there.`);
                }} else if (data.correct_row === row) {{
                    alert(`Jar ${{jar}} actually belongs in this row. Double-check the placement.`);
                }} else {{
                    alert(`Jar ${{jar}} not found in known jar list.`);
                }}
            }} else {{
                alert("Error: " + (data.error || "Unknown issue."));
            }}
        }}
        </script>
    </body>
    </html>
    """
    return render_template_string(html)


@app.route("/misplaced")
def misplaced_page():
    rows = "".join([
        f"<tr><td>{m['time']}</td><td>{m['jar']}</td><td>{m['found_in']}</td><td>{m['correct_row'] or 'Unknown'}</td></tr>"
        for m in misplaced_jars
    ])
    html = f"""
    <html><head><title>Misplaced Jars</title>
    <style>
        body {{ font-family: sans-serif; background: #fafafa; padding: 20px; }}
        table {{ width: 80%; border-collapse: collapse; margin: auto; background: white; }}
        th, td {{ padding: 8px; border: 1px solid #ccc; text-align: center; }}
        th {{ background: #eee; }}
    </style></head><body>
    <h1>Misplaced Jars Log</h1>
    <table>
    <tr><th>Time</th><th>Jar</th><th>Found In</th><th>Should Be In</th></tr>
    {rows or "<tr><td colspan='4'>No misplaced jars recorded.</td></tr>"}
    </table>
    <br><a href="/">⬅ Back to Home</a>
    </body></html>
    """
    return render_template_string(html)

@app.route("/event_log")
def event_log_page():
    """Display the event log in a user-friendly format."""
    # Get the last 100 events (more than the API endpoint)
    events = event_log[-100:] if event_log else []
    
    # Reverse to show newest first
    events_reversed = list(reversed(events))
    
    rows = "".join([
        f"<tr><td>{event['time']}</td><td>Row {event['row']}</td><td>{event['event']}</td><td>{event['distance']} cm</td></tr>"
        for event in events_reversed
    ])
    
    html = f"""
    <html>
    <head>
        <title>Event Log - Jar Tracking System</title>
        <style>
            body {{ font-family: sans-serif; background: #fafafa; padding: 20px; }}
            .header {{ text-align: center; margin-bottom: 20px; }}
            .stats {{ background: white; padding: 15px; border-radius: 8px; 
                     box-shadow: 0 2px 6px rgba(0,0,0,0.1); margin-bottom: 20px; 
                     display: inline-block; margin-right: 20px; }}
            table {{ width: 90%; border-collapse: collapse; margin: auto; background: white;
                    border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); }}
            th, td {{ padding: 12px; border: 1px solid #ddd; text-align: left; }}
            th {{ background: #f8f9fa; font-weight: bold; }}
            tr:nth-child(even) {{ background: #f9f9f9; }}
            tr:hover {{ background: #e8f4f8; }}
            .back-button {{ display: inline-block; padding: 10px 20px; background: #007bff; 
                           color: white; border-radius: 5px; text-decoration: none; 
                           margin: 20px auto; display: block; width: fit-content; }}
            .refresh-button {{ display: inline-block; padding: 8px 16px; background: #28a745; 
                              color: white; border-radius: 5px; text-decoration: none; 
                              margin-left: 10px; }}
        </style>
        <script>
            // Auto-refresh every 10 seconds
            setTimeout(() => location.reload(), 10000);
        </script>
    </head>
    <body>
        <div class="header">
            <h1>Event Log - Jar Tracking System</h1>
            <div class="stats">
                <strong>Total Events:</strong> {len(event_log)}
            </div>
            <div class="stats">
                <strong>Showing:</strong> Last {len(events)} events
            </div>
            <a href="/event_log" class="refresh-button">🔄 Refresh</a>
        </div>
        
        <table>
            <tr>
                <th>Timestamp</th>
                <th>Location</th>
                <th>Event</th>
                <th>Distance</th>
            </tr>
            {rows or "<tr><td colspan='4' style='text-align: center; font-style: italic; color: #666;'>No events recorded yet.</td></tr>"}
        </table>
        
        <a href="/" class="back-button">⬅ Back to Home</a>
    </body>
    </html>
    """
    return render_template_string(html)



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
