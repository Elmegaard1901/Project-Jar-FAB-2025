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
SERIAL_PORT = "/dev/cu.usbmodem101"  # Adjust (e.g. "COM3" on Windows)
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
jar_status = {}  # stores jar status: {"jar_id": {"status": "present/missing/misplaced", "row": 1, "time": "timestamp"}}

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
                    print(f"Warning: Incomplete data received: {line}")
                    continue
                try:
                    # Arduino sends distance1,state1,distance2,state2 and optionally lower,upper thresholds
                    # Convert Arduino state values (50/0) to boolean (1/0)
                    dist1, state1_raw, dist2, state2_raw = float(parts[0]), int(parts[1]), float(parts[2]), int(parts[3])
                    state1 = 1 if state1_raw > 0 else 0
                    state2 = 1 if state2_raw > 0 else 0
                    # If Arduino also sends threshold values, use them for visualization
                    lower_threshold = float(parts[4]) if len(parts) > 4 else 30.0
                    upper_threshold = float(parts[5]) if len(parts) > 5 else 40.0
                except (ValueError, IndexError) as e:
                    print(f"Error parsing data: {line} - {e}")
                    continue

            latest_data.update({
                "dist1": dist1, "state1": state1,
                "dist2": dist2, "state2": state2,
                "lower": lower_threshold, "upper": upper_threshold
            })

            # # Debug output for real sensor data (not mock mode)
            # if not MOCK_MODE and arduino is not None:
            #     print(f"Sensor data: D1={dist1:.1f}cm S1={state1}, D2={dist2:.1f}cm S2={state2}")

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
                print(f"Event logged: Row 1 needs checking (distance: {dist1:.1f} cm)")
            if prev_state2 is not None and prev_state2 != state2 and state2 == 1:
                event_log.append({
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "row": 2,
                    "event": "Needs checking",
                    "distance": round(dist2, 1)
                })
                alerts[2] = True
                print(f"Event logged: Row 2 needs checking (distance: {dist2:.1f} cm)")

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

@app.route("/update_jar_status", methods=["POST"])
def update_jar_status():
    """Update the status of a jar (present/missing)"""
    data = request.json
    jar_id = data.get("jar_id")
    status = data.get("status")  # "present" or "missing"
    row = data.get("row")

    if not jar_id or not status or not row:
        return jsonify({"success": False, "error": "Missing required data"}), 400

    if status not in ["present", "missing"]:
        return jsonify({"success": False, "error": "Invalid status"}), 400

    # Verify jar belongs to this row
    if row not in row_jars or jar_id not in row_jars[row]:
        return jsonify({"success": False, "error": "Jar not found in specified row"}), 400

    # Update jar status
    jar_status[jar_id] = {
        "status": status,
        "row": row,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    return jsonify({"success": True, "message": f"Jar {jar_id} marked as {status}"})

@app.route("/get_jar_status/<int:row>")
def get_jar_status(row):
    """Get the status of all jars in a specific row"""
    if row not in row_jars:
        return jsonify({"success": False, "error": "Invalid row"}), 404

    row_status = {}
    for jar_id in row_jars[row]:
        if jar_id in jar_status:
            row_status[jar_id] = jar_status[jar_id]
        else:
            row_status[jar_id] = {"status": "unchecked", "row": row, "time": None}

    return jsonify({"success": True, "jars": row_status})


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
        <a class="button" href="/misplaced">View Missing & Misplaced Jars</a>

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

    # Create individual jar items with checkboxes
    jar_items = ""
    for jar in row_jars[row]:
        jar_items += f"""
        <div class='jar-item'>
            <div class='jar-info'>
                <span class='jar-id'>{jar}</span>
            </div>
            <div class='jar-controls'>
                <label class='checkbox-container present'>
                    <input type='checkbox' class='jar-checkbox' data-jar='{jar}' data-status='present'>
                    <span class='checkmark present-check'></span>
                    <span class='label-text'>Present</span>
                </label>
                <label class='checkbox-container missing'>
                    <input type='checkbox' class='jar-checkbox' data-jar='{jar}' data-status='missing'>
                    <span class='checkmark missing-check'></span>
                    <span class='label-text'>Missing</span>
                </label>
            </div>
        </div>
        """

    html = f"""
    <html>
    <head>
        <title>Checklist - Row {row}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{ 
                font-family: sans-serif; 
                background: #f9f9f9; 
                padding: 20px;
                color: #333;
            }}
            
            .container {{
                max-width: 800px;
                margin: 0 auto;
            }}
            
            .card {{
                background: white;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 6px rgba(0,0,0,0.1);
                margin: 10px 0;
            }}
            
            h1 {{
                color: #333;
                margin-bottom: 10px;
            }}
            
            p {{
                color: #666;
                margin-bottom: 20px;
            }}
            
            .jar-item {{
                display: flex;
                align-items: center;
                justify-content: space-between;
                padding: 15px 0;
                border-bottom: 1px solid #eee;
            }}
            
            .jar-item:last-child {{
                border-bottom: none;
            }}
            
            .jar-info {{
                flex: 1;
            }}
            
            .jar-id {{
                font-weight: 600;
                font-size: 1.1em;
                color: #333;
                background: #f8f9fa;
                padding: 6px 10px;
                border-radius: 4px;
                display: inline-block;
            }}
            
            .jar-controls {{
                display: flex;
                gap: 20px;
                align-items: center;
            }}
            
            .checkbox-container {{
                position: relative;
                display: flex;
                align-items: center;
                cursor: pointer;
                user-select: none;
                gap: 8px;
            }}
            
            .checkbox-container input {{
                position: absolute;
                opacity: 0;
                cursor: pointer;
                height: 0;
                width: 0;
            }}
            
            .checkmark {{
                height: 18px;
                width: 18px;
                border-radius: 3px;
                border: 2px solid #ddd;
                position: relative;
                transition: all 0.2s ease;
            }}
            
            .present-check {{
                border-color: #4CAF50;
            }}
            
            .missing-check {{
                border-color: #f44336;
            }}
            
            .checkbox-container input:checked ~ .present-check {{
                background-color: #4CAF50;
                border-color: #4CAF50;
            }}
            
            .checkbox-container input:checked ~ .missing-check {{
                background-color: #f44336;
                border-color: #f44336;
            }}
            
            .checkmark:after {{
                content: "";
                position: absolute;
                display: none;
                left: 5px;
                top: 1px;
                width: 4px;
                height: 8px;
                border: solid white;
                border-width: 0 2px 2px 0;
                transform: rotate(45deg);
            }}
            
            .checkbox-container input:checked ~ .checkmark:after {{
                display: block;
            }}
            
            .label-text {{
                font-weight: 500;
                font-size: 0.9em;
            }}
            
            .present .label-text {{
                color: #4CAF50;
            }}
            
            .missing .label-text {{
                color: #f44336;
            }}
            
            .action-section {{
                margin-bottom: 20px;
            }}
            
            .action-section h3 {{
                color: #333;
                margin-bottom: 15px;
                font-size: 1.2em;
            }}
            
            .button {{
                display: inline-block;
                padding: 10px 20px;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                font-weight: 600;
                text-decoration: none;
                transition: background-color 0.2s ease;
                font-size: 0.9em;
                margin: 5px;
            }}
            
            .btn-primary {{
                background: #007bff;
                color: white;
            }}
            
            .btn-primary:hover {{
                background: #0056b3;
            }}
            
            .btn-success {{
                background: #4CAF50;
                color: white;
            }}
            
            .btn-success:hover {{
                background: #45a049;
            }}
            
            .input-group {{
                display: flex;
                gap: 10px;
                align-items: center;
                flex-wrap: wrap;
            }}
            
            .form-input {{
                padding: 10px;
                border: 1px solid #ddd;
                border-radius: 5px;
                font-size: 1em;
                flex: 1;
                min-width: 200px;
            }}
            
            .form-input:focus {{
                outline: none;
                border-color: #007bff;
            }}
            
            .summary {{
                background: #f8f9fa;
                padding: 15px;
                border-radius: 5px;
                margin-top: 15px;
                display: none;
                border: 1px solid #dee2e6;
            }}
            
            .summary.show {{
                display: block;
            }}
            
            @media (max-width: 600px) {{
                .jar-item {{
                    flex-direction: column;
                    align-items: flex-start;
                    gap: 10px;
                }}
                
                .jar-controls {{
                    width: 100%;
                    justify-content: flex-start;
                }}
                
                .input-group {{
                    flex-direction: column;
                    align-items: stretch;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Checklist - Row {row}</h1>
            <p>Check each jar's status and manage misplaced items</p>
            
            <div class="card">
                {jar_items}
            </div>
            
            <div class="card">
                <div class="action-section">
                    <h3>Quick Actions</h3>
                    <button class="button btn-success" onclick="clearAlert({row})">Clear Alert for Row {row}</button>
                    <button class="button btn-primary" onclick="generateSummary()">Generate Summary</button>
                </div>
                
                <div class="action-section">
                    <h3>Report Misplaced Jar</h3>
                    <div class="input-group">
                        <input id="jar_{row}" class="form-input" placeholder="Enter Jar ID (e.g., R0244)">
                        <button class="button btn-primary" onclick="markWrongJar({row})">Report Misplaced</button>
                    </div>
                </div>
                
                <div id="summary" class="summary">
                    <h4>Current Status Summary</h4>
                    <div id="summary-content"></div>
                </div>
            </div>
        </div>
        
        <a href="/">⬅ Back to Home</a>

        <script>
        // Handle checkbox interactions
        document.addEventListener('DOMContentLoaded', function() {{
            const checkboxes = document.querySelectorAll('.jar-checkbox');
            
            // Load existing jar status
            loadJarStatus();
            
            checkboxes.forEach(checkbox => {{
                checkbox.addEventListener('change', function() {{
                    const jar = this.dataset.jar;
                    const status = this.dataset.status;
                    
                    if (this.checked) {{
                        // Uncheck other checkboxes for the same jar
                        checkboxes.forEach(cb => {{
                            if (cb.dataset.jar === jar && cb !== this) {{
                                cb.checked = false;
                            }}
                        }});
                        
                        // Save status to server
                        updateJarStatus(jar, status);
                        console.log(`Jar ${{jar}} marked as ${{status}}`);
                    }}
                }});
            }});
        }});

        async function loadJarStatus() {{
            try {{
                const res = await fetch(`/get_jar_status/{row}`);
                const data = await res.json();
                
                if (data.success) {{
                    const checkboxes = document.querySelectorAll('.jar-checkbox');
                    
                    Object.entries(data.jars).forEach(([jarId, jarData]) => {{
                        if (jarData.status !== 'unchecked') {{
                            const checkbox = document.querySelector(`[data-jar="${{jarId}}"][data-status="${{jarData.status}}"]`);
                            if (checkbox) {{
                                checkbox.checked = true;
                            }}
                        }}
                    }});
                }}
            }} catch (error) {{
                console.error('Error loading jar status:', error);
            }}
        }}

        async function updateJarStatus(jarId, status) {{
            try {{
                const res = await fetch('/update_jar_status', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        jar_id: jarId,
                        status: status,
                        row: {row}
                    }})
                }});
                
                const data = await res.json();
                if (!data.success) {{
                    alert(`Error updating jar status: ${{data.error}}`);
                }}
            }} catch (error) {{
                console.error('Error updating jar status:', error);
                alert('Error updating jar status');
            }}
        }}

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
            if (!jar) {{
                alert("Please enter a jar ID");
                return;
            }}

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
                document.getElementById(`jar_${{row}}`).value = '';
            }} else {{
                alert("Error: " + (data.error || "Unknown issue."));
            }}
        }}
        
        function generateSummary() {{
            const checkboxes = document.querySelectorAll('.jar-checkbox:checked');
            const summary = {{
                present: [],
                missing: []
            }};
            
            checkboxes.forEach(cb => {{
                const jar = cb.dataset.jar;
                const status = cb.dataset.status;
                summary[status].push(jar);
            }});
            
            const totalJars = {len(row_jars[row])};
            const checkedJars = checkboxes.length;
            const uncheckedJars = totalJars - checkedJars;
            
            let summaryHTML = `
                <p><strong>Total Jars:</strong> ${{totalJars}}</p>
                <p><strong>Checked:</strong> ${{checkedJars}} | <strong>Unchecked:</strong> ${{uncheckedJars}}</p>
            `;
            
            if (summary.present.length > 0) {{
                summaryHTML += `<p><strong>Present (${{summary.present.length}}):</strong> ${{summary.present.join(', ')}}</p>`;
            }}
            if (summary.missing.length > 0) {{
                summaryHTML += `<p><strong>Missing (${{summary.missing.length}}):</strong> ${{summary.missing.join(', ')}}</p>`;
            }}
            
            document.getElementById('summary-content').innerHTML = summaryHTML;
            document.getElementById('summary').classList.add('show');
        }}
        </script>
    </body>
    </html>
    """
    return render_template_string(html)


@app.route("/misplaced")
def misplaced_page():
    # Get all missing jars from jar_status
    missing_jars = []
    for jar_id, status_info in jar_status.items():
        if status_info['status'] == 'missing':
            # Find which row this jar belongs to
            correct_row = None
            for row, jars in row_jars.items():
                if jar_id in jars:
                    correct_row = row
                    break
            
            missing_jars.append({
                'jar': jar_id,
                'row': correct_row,
                'time': status_info['time']
            })

    # Create summary statistics
    total_jars = sum(len(jars) for jars in row_jars.values())
    total_checked = len([j for j in jar_status.values() if j['status'] in ['present', 'missing']])
    total_present = len([j for j in jar_status.values() if j['status'] == 'present'])
    total_missing = len(missing_jars)
    total_misplaced = len(misplaced_jars)

    # Create tables
    missing_rows = "".join([
        f"<tr><td>{m['time'] or 'N/A'}</td><td>{m['jar']}</td><td>Row {m['row'] or 'Unknown'}</td><td><span class='status-missing'>Missing</span></td></tr>"
        for m in missing_jars
    ])
    
    misplaced_rows = "".join([
        f"<tr><td>{m['time']}</td><td>{m['jar']}</td><td>Row {m['correct_row'] or 'Unknown'}</td><td><span class='status-misplaced'>Found in Row {m['found_in']}</span></td></tr>"
        for m in misplaced_jars
    ])

    all_rows = missing_rows + misplaced_rows

    html = f"""
    <html>
    <head>
        <title>Misplaced and Missing Jars</title>
        <style>
            body {{ font-family: sans-serif; background: #f9f9f9; padding: 20px; }}
            .container {{ max-width: 1000px; margin: 0 auto; }}
            .card {{ background: white; padding: 20px; border-radius: 8px;
                     box-shadow: 0 2px 6px rgba(0,0,0,0.1); margin: 10px 0; }}
            .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px; }}
            .stat-item {{ background: white; padding: 15px; border-radius: 8px; text-align: center;
                         box-shadow: 0 2px 6px rgba(0,0,0,0.1); }}
            .stat-number {{ font-size: 2em; font-weight: bold; margin-bottom: 5px; }}
            .stat-label {{ color: #666; font-size: 0.9em; }}
            .stat-total {{ color: #333; }}
            .stat-present {{ color: #4CAF50; }}
            .stat-missing {{ color: #f44336; }}
            .stat-misplaced {{ color: #ff9800; }}
            table {{ width: 100%; border-collapse: collapse; margin: auto; background: white; }}
            th, td {{ padding: 12px; border: 1px solid #ddd; text-align: left; }}
            th {{ background: #f8f9fa; font-weight: bold; }}
            tr:nth-child(even) {{ background: #f9f9f9; }}
            tr:hover {{ background: #e8f4f8; }}
            .status-missing {{ background: #f44336; color: white; padding: 4px 8px; border-radius: 4px; font-size: 0.8em; }}
            .status-misplaced {{ background: #ff9800; color: white; padding: 4px 8px; border-radius: 4px; font-size: 0.8em; }}
            .section-title {{ color: #333; margin: 20px 0 10px 0; }}
            .empty-state {{ text-align: center; color: #666; font-style: italic; padding: 30px; }}
            .button {{ display: inline-block; padding: 10px 20px; background: #007bff; color: white;
                      border-radius: 5px; text-decoration: none; margin: 10px 5px; }}
            .btn-export {{ background: #28a745; }}
            .btn-refresh {{ background: #17a2b8; }}
        </style>
        <script>
            // Auto-refresh every 30 seconds
            setTimeout(() => location.reload(), 30000);
        </script>
    </head>
    <body>
        <div class="container">
            <h1>Misplaced and Missing Jars Overview</h1>
            <p>Comprehensive tracking of jar status across all monitored rows</p>
            
            <div class="stats-grid">
                <div class="stat-item">
                    <div class="stat-number stat-total">{total_jars}</div>
                    <div class="stat-label">Total Jars</div>
                </div>
                <div class="stat-item">
                    <div class="stat-number stat-present">{total_present}</div>
                    <div class="stat-label">Present</div>
                </div>
                <div class="stat-item">
                    <div class="stat-number stat-missing">{total_missing}</div>
                    <div class="stat-label">Missing</div>
                </div>
                <div class="stat-item">
                    <div class="stat-number stat-misplaced">{total_misplaced}</div>
                    <div class="stat-label">Misplaced</div>
                </div>
                <div class="stat-item">
                    <div class="stat-number">{total_jars - total_checked}</div>
                    <div class="stat-label">Unchecked</div>
                </div>
            </div>

            <div class="card">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                    <h2 class="section-title">All Issues</h2>
                    <div>
                        <a href="/misplaced" class="button btn-refresh">🔄 Refresh</a>
                        <button onclick="exportData()" class="button btn-export">📊 Export Data</button>
                    </div>
                </div>
                
                {f'''
                <table>
                    <tr>
                        <th>Timestamp</th>
                        <th>Jar ID</th>
                        <th>Should Be In</th>
                        <th>Status</th>
                    </tr>
                    {all_rows}
                </table>
                ''' if (missing_jars or misplaced_jars) else '<div class="empty-state">🎉 No missing or misplaced jars found! All jars are properly accounted for.</div>'}
            </div>

            <div class="card">
                <h3>Missing Jars Details ({total_missing})</h3>
                {f'''
                <table>
                    <tr>
                        <th>Timestamp</th>
                        <th>Jar ID</th>
                        <th>Should Be In</th>
                        <th>Status</th>
                    </tr>
                    {missing_rows}
                </table>
                ''' if missing_jars else '<div class="empty-state">No missing jars recorded.</div>'}
            </div>

            <div class="card">
                <h3>Misplaced Jars Details ({total_misplaced})</h3>
                {f'''
                <table>
                    <tr>
                        <th>Timestamp</th>
                        <th>Jar ID</th>
                        <th>Should Be In</th>
                        <th>Status</th>
                    </tr>
                    {misplaced_rows}
                </table>
                ''' if misplaced_jars else '<div class="empty-state">No misplaced jars recorded.</div>'}
            </div>

            <div style="text-align: center; margin-top: 20px;">
                <a href="/" class="button">⬅ Back to Home</a>
                <a href="/event_log" class="button">📋 View Event Log</a>
            </div>
        </div>

        <script>
        function exportData() {{
            const data = {{
                timestamp: new Date().toISOString(),
                summary: {{
                    total_jars: {total_jars},
                    present: {total_present},
                    missing: {total_missing},
                    misplaced: {total_misplaced},
                    unchecked: {total_jars - total_checked}
                }},
                missing_jars: {missing_jars},
                misplaced_jars: {misplaced_jars}
            }};
            
            const blob = new Blob([JSON.stringify(data, null, 2)], {{type: 'application/json'}});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `jar_status_${{new Date().toISOString().split('T')[0]}}.json`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }}
        </script>
    </body>
    </html>
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
