# JAR Tracking System - FAB 2025

A real-time jar tracking and monitoring system built for the University of Copenhagen (KU) FAB course 2025. This project combines Arduino-based ultrasonic sensors with a Flask web application to monitor jar placement and movement across multiple storage rows.

## 🎯 Project Overview

The JAR Tracking System monitors jar placement using ultrasonic sensors and provides real-time alerts when jars are moved or misplaced. The system features a web-based interface with QR code generation for easy access to row-specific checklists.

### Key Features

- **Real-time monitoring** of jar placement using HC-SR04 ultrasonic sensors
- **Web-based dashboard** with live updates via Server-Sent Events (SSE)
- **QR code generation** for quick access to row-specific checklists
- **Alert system** with visual and audio notifications
- **Event logging** for tracking jar movements over time
- **Misplaced jar tracking** to identify incorrectly placed items
- **Mock mode** for testing without hardware

**⚠️ Network Requirement**: Computer and mobile device must be on the same Wi-Fi network for QR codes to work properly.

## 🏗️ System Architecture

The system consists of two main components:

1. **Arduino Hardware**: Ultrasonic sensors with hysteresis filtering for stable readings
2. **Flask Web Application**: Real-time web interface with RESTful API

### Hardware Setup

- **2x HC-SR04 Ultrasonic Sensors** for distance measurement
- **Arduino Uno/Nano** for sensor control and data collection
- **LEDs** for visual status indication
- **Serial communication** (USB) between Arduino and computer

### Software Stack

- **Backend**: Python Flask with real-time SSE
- **Frontend**: HTML/CSS/JavaScript with Chart.js for data visualization
- **Communication**: Serial communication via pySerial
- **Additional**: QR code generation, PIL for image processing

## 📁 Project Structure

```
Project-Jar-FAB-2025/
├── jar_tracking_website.py    # Main Flask application
├── requirements.txt           # Python dependencies
├── README.md                 # Project documentation
└── arduino-code/
    ├── range_sensor_ex.ino   # Single sensor example code
    └── two_sensor_hysteresis.ino  # Main dual-sensor code with hysteresis
```

## ⚙️ Installation & Setup

### Prerequisites

- Python 3.7+ 
- Arduino IDE
- HC-SR04 ultrasonic sensors
- Arduino Uno/Nano

### Python Environment Setup

1. Clone the repository:
```bash
git clone https://github.com/Elmegaard1901/Project-Jar-FAB-2025.git
cd Project-Jar-FAB-2025
```

2. Install Python dependencies:
```bash
pip install -r requirements.txt
```

### Arduino Setup

1. Open `arduino-code/two_sensor_hysteresis.ino` in Arduino IDE
2. Connect the hardware according to the wiring diagram:

#### Wiring Diagram

**Sensor 1:**
- VCC → 5V
- GND → GND  
- Trig → Pin 7
- Echo → Pin 8
- LED → Pin 2

**Sensor 2:**
- VCC → 5V
- GND → GND
- Trig → Pin 12
- Echo → Pin 13
- LED → Pin 4

3. Upload the code to your Arduino
4. Note the serial port (e.g., `/dev/cu.usbmodem1101` on macOS, `COM3` on Windows)

### Configuration

1. Edit `jar_tracking_website.py` and update the serial port:
```python
SERIAL_PORT = "/dev/cu.usbmodem1101"  # Update for your system
```

2. Customize jar assignments per row:
```python
row_jars = {
    1: ["H004040", "H004041"],
    2: ["R0244", "R0245", "R0246", "R0247", "R47376", "R47346", "R47347"],
}
```

## 🚀 Usage

### Starting the System

1. Connect Arduino via USB
2. Run the Flask application:
```bash
python jar_tracking_website.py
```

3. Open your browser and navigate to:
```
http://localhost:8000
```

### Mock Mode (Testing without Hardware)

To test without Arduino hardware, set mock mode in the code:
```python
MOCK_MODE = True
```

### Web Interface Features

#### Main Dashboard (`/`)
- View current alert status for all rows
- Access QR codes for each row
- Navigate to live tracking and logs

#### Live Tracking (`/live`)
- Real-time distance measurements
- Live charts showing sensor data
- Visual sensor status indicators

#### Row Checklists (`/checklist/<row>`)
- QR code accessible checklists
- Clear alerts for specific rows
- Mark misplaced jars

#### Event Log (`/event_log`)
- Historical view of all jar movements
- Timestamp and distance information
- Auto-refresh functionality

#### Misplaced Jars (`/misplaced`)
- Track incorrectly placed jars
- Shows correct vs. found locations
- Helps with reorganization

## 🔧 Technical Details

### Hysteresis Filtering

The Arduino code implements hysteresis filtering to prevent rapid on/off switching:

- **Lower Threshold**: 30.0 cm (triggers "needs checking" state)
- **Upper Threshold**: 40.0 cm (clears "needs checking" state)

This prevents false alerts when objects hover near the threshold.

### Serial Communication Protocol

Arduino sends comma-separated values:
```
distance1,state1,distance2,state2,lower_threshold,upper_threshold
```

Example: `35.2,0,28.1,1,30.0,40.0`

### API Endpoints

- `GET /` - Main dashboard
- `GET /live` - Live tracking page  
- `GET /events` - SSE stream for real-time updates
- `GET /log` - JSON event log (last 50 events)
- `GET /alerts` - Current alert status
- `POST /clear_alert/<row>` - Clear alert for specific row
- `POST /mark_wrong_jar` - Mark jar as misplaced
- `GET /qr/<row>` - Generate QR code for row checklist

## 🎛️ Configuration Options

### Sensor Thresholds
Adjust in Arduino code:
```cpp
const float LOWER_THRESHOLD = 30.0;  // cm
const float UPPER_THRESHOLD = 40.0;  // cm
```

### Serial Settings
```python
SERIAL_PORT = "/dev/cu.usbmodem1101"  # Adjust for your system
BAUD_RATE = 115200
```

### Jar Database
Update jar assignments in `row_jars` dictionary:
```python
row_jars = {
    1: ["JAR001", "JAR002"],
    2: ["JAR003", "JAR004", "JAR005"],
    # Add more rows as needed
}
```

## 🐛 Troubleshooting

### Common Issues

1. **Serial Connection Error**
   - Check if Arduino is connected
   - Verify correct serial port in code
   - Ensure no other programs are using the serial port

2. **Sensor Not Reading**
   - Check wiring connections
   - Verify 5V power supply
   - Test with single sensor example code

3. **Web Interface Not Loading**
   - Check if Flask is running on correct port
   - Verify no firewall blocking port 8000
   - Try accessing via `127.0.0.1:8000`

### Mock Mode Testing

Use mock mode to test the web interface without hardware:
```python
MOCK_MODE = True
```

## 📊 Performance Considerations

- **Sensor Reading Rate**: ~10 Hz (100ms delay)
- **Web Update Rate**: 5 Hz (200ms via SSE)
- **Chart Data Points**: Limited to last 100 points for performance
- **Event Log**: Stores unlimited events, displays last 100

## 🔮 Future Enhancements

- Database storage for persistent data
- Multiple sensor rows support
- Mobile app interface
- Email/SMS alert notifications
- Advanced analytics and reporting
- Integration with inventory management systems

## 👥 Contributors

- **Course**: FAB 2025, University of Copenhagen (KU)
- **Repository**: [Project-Jar-FAB-2025](https://github.com/Elmegaard1901/Project-Jar-FAB-2025)

## 📝 License

This project is developed for educational purposes as part of the FAB course at the University of Copenhagen.

---

**Note**: This system is designed for monitoring glass jar storage in laboratory or industrial environments. Ensure proper safety measures when working with electronic components and follow your institution's safety guidelines.
