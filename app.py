from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import mysql.connector
import asyncio
import json
import random
from datetime import datetime
from typing import List

app = FastAPI()

# WebSocket connections manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                disconnected.append(connection)
        
        # Remove disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

manager = ConnectionManager()

# Database connection - UPDATE THESE CREDENTIALS
def get_db_connection():
    try:
        return mysql.connector.connect(
            host="localhost",
            user="root",  # Change this to your MySQL username
            password="pass@123",  # Change this to your MySQL password
            database="security_system"  # Make sure this database exists
        )
    except mysql.connector.Error as err:
        print(f"Database connection error: {err}")
        return None

# Test database connection
@app.get("/test-db")
async def test_database():
    conn = get_db_connection()
    if conn:
        conn.close()
        return {"status": "Database connection successful"}
    else:
        return {"status": "Database connection failed"}

# Simulate face detection and insert alert
@app.post("/simulate-detection")
async def simulate_detection():
    conn = get_db_connection()
    if not conn:
        return {"error": "Database connection failed"}
    
    cursor = conn.cursor()
    
    try:
        # First check if blacklisted_persons exist
        cursor.execute("SELECT id FROM blacklisted_persons LIMIT 3")
        persons = cursor.fetchall()
        
        if not persons:
            # Create sample data if none exists
            cursor.execute("""
                INSERT INTO blacklisted_persons (name, threat_level) VALUES 
                ('John Dangerous', 'HIGH'),
                ('Jane Suspect', 'MEDIUM'),
                ('Bob Criminal', 'HIGH')
            """)
            conn.commit()
            cursor.execute("SELECT id FROM blacklisted_persons LIMIT 3")
            persons = cursor.fetchall()
        
        # Simulate random detection
        cameras = ["CAM_001_Entrance", "CAM_002_Lobby", "CAM_003_Parking"]
        
        person_id = random.choice(persons)[0]
        camera = random.choice(cameras)
        confidence = round(random.uniform(75.0, 99.9), 2)
        
        # Insert into security_alerts (this will trigger the database trigger)
        cursor.execute("""
            INSERT INTO security_alerts (person_id, camera_location, confidence_score) 
            VALUES (%s, %s, %s)
        """, (person_id, camera, confidence))
        
        alert_id = cursor.lastrowid
        conn.commit()
        
        return {"message": "Detection simulated", "alert_id": alert_id}
        
    except Exception as e:
        return {"error": f"Database error: {str(e)}"}
    finally:
        cursor.close()
        conn.close()

# Background task to monitor notification queue
async def monitor_notifications():
    while True:
        try:
            conn = get_db_connection()
            if not conn:
                await asyncio.sleep(5)
                continue
                
            cursor = conn.cursor(dictionary=True)
            
            # Check for unprocessed notifications
            cursor.execute("""
                SELECT nq.*, sa.person_id, sa.camera_location, sa.confidence_score, 
                       sa.detection_time, bp.name, bp.threat_level
                FROM notification_queue nq
                JOIN security_alerts sa ON nq.alert_id = sa.id
                JOIN blacklisted_persons bp ON sa.person_id = bp.id
                WHERE nq.processed = FALSE
            """)
            
            notifications = cursor.fetchall()
            
            for notification in notifications:
                alert_data = {
                    "alert_id": notification['alert_id'],
                    "person_name": notification['name'],
                    "threat_level": notification['threat_level'],
                    "camera_location": notification['camera_location'],
                    "confidence_score": float(notification['confidence_score']),
                    "detection_time": notification['detection_time'].isoformat(),
                    "message": notification['message']
                }
                
                # Send to frontend via WebSocket
                await manager.broadcast(json.dumps(alert_data))
                
                # Mark as processed
                cursor.execute(
                    "UPDATE notification_queue SET processed = TRUE WHERE id = %s", 
                    (notification['id'],)
                )
            
            conn.commit()
            cursor.close()
            conn.close()
            
        except Exception as e:
            print(f"Error monitoring notifications: {e}")
        
        await asyncio.sleep(2)  # Check every 2 seconds

# WebSocket endpoint for real-time alerts
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Keep connection alive
    except Exception as e:
        print(f"WebSocket error: {e}")
        manager.disconnect(websocket)

# Get all alerts
@app.get("/alerts")
async def get_alerts():
    conn = get_db_connection()
    if not conn:
        return {"error": "Database connection failed"}
    
    cursor = conn.cursor(dictionary=True)
    
    try:
        cursor.execute("""
            SELECT sa.*, bp.name, bp.threat_level
            FROM security_alerts sa
            JOIN blacklisted_persons bp ON sa.person_id = bp.id
            ORDER BY sa.detection_time DESC
            LIMIT 50
        """)
        
        alerts = cursor.fetchall()
        
        # Convert datetime to string for JSON serialization
        for alert in alerts:
            if alert['detection_time']:
                alert['detection_time'] = alert['detection_time'].isoformat()
            alert['confidence_score'] = float(alert['confidence_score'])
        
        return alerts
    except Exception as e:
        return {"error": f"Database error: {str(e)}"}
    finally:
        cursor.close()
        conn.close()

# Start background monitoring on startup
@app.on_event("startup")
async def startup_event():
    print("Starting background notification monitor...")
    asyncio.create_task(monitor_notifications())

# Serve the frontend
@app.get("/", response_class=FileResponse)
async def get_frontend():
    return FileResponse("frontend.html")