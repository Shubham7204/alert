from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import mysql.connector
import asyncio
import json
import random
from datetime import datetime
from typing import Dict, List

app = FastAPI()

# Enhanced WebSocket connections manager for multiple video streams
class VideoConnectionManager:
    def __init__(self):
        # Dictionary to store connections by video_id
        self.video_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, video_id: str):
        await websocket.accept()
        if video_id not in self.video_connections:
            self.video_connections[video_id] = []
        self.video_connections[video_id].append(websocket)
        print(f"Client connected to video stream {video_id}")

    def disconnect(self, websocket: WebSocket, video_id: str):
        if video_id in self.video_connections:
            if websocket in self.video_connections[video_id]:
                self.video_connections[video_id].remove(websocket)
            # Clean up empty video streams
            if not self.video_connections[video_id]:
                del self.video_connections[video_id]
        print(f"Client disconnected from video stream {video_id}")

    async def broadcast_to_video(self, video_id: str, message: str):
        """Send message to all clients connected to specific video stream"""
        if video_id not in self.video_connections:
            return
        
        disconnected = []
        for connection in self.video_connections[video_id]:
            try:
                await connection.send_text(message)
            except:
                disconnected.append(connection)
        
        # Remove disconnected clients
        for conn in disconnected:
            self.disconnect(conn, video_id)

    async def broadcast_to_all(self, message: str):
        """Send message to all connected clients across all video streams"""
        for video_id in list(self.video_connections.keys()):
            await self.broadcast_to_video(video_id, message)

    def get_active_streams(self) -> List[str]:
        """Get list of video streams with active connections"""
        return list(self.video_connections.keys())

    def get_connection_count(self, video_id: str) -> int:
        """Get number of active connections for a video stream"""
        return len(self.video_connections.get(video_id, []))

manager = VideoConnectionManager()

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

# Simulate face detection for specific video
@app.post("/simulate-detection/{video_id}")
async def simulate_detection_for_video(video_id: str):
    conn = get_db_connection()
    if not conn:
        return {"error": "Database connection failed"}
    
    cursor = conn.cursor()
    
    try:
        # Check if blacklisted_persons exist
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
        
        # Simulate detection for specific video
        cameras = [f"CAM_{video_id}_Entrance", f"CAM_{video_id}_Main", f"CAM_{video_id}_Exit"]
        
        person_id = random.choice(persons)[0]
        camera = random.choice(cameras)
        confidence = round(random.uniform(75.0, 99.9), 2)
        
        # Insert with video_id
        cursor.execute("""
            INSERT INTO security_alerts (person_id, camera_location, video_id, confidence_score) 
            VALUES (%s, %s, %s, %s)
        """, (person_id, camera, video_id, confidence))
        
        alert_id = cursor.lastrowid
        conn.commit()
        
        return {"message": f"Detection simulated for video {video_id}", "alert_id": alert_id}
        
    except Exception as e:
        return {"error": f"Database error: {str(e)}"}
    finally:
        cursor.close()
        conn.close()

# Keep the original endpoint for backward compatibility
@app.post("/simulate-detection")
async def simulate_detection():
    return await simulate_detection_for_video("general")

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
                SELECT nq.*, sa.person_id, sa.camera_location, sa.video_id, sa.confidence_score, 
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
                    "video_id": notification['video_id'],
                    "confidence_score": float(notification['confidence_score']),
                    "detection_time": notification['detection_time'].isoformat(),
                    "message": notification['message']
                }
                
                # Send to specific video stream clients
                video_id = notification['video_id'] or "general"
                await manager.broadcast_to_video(video_id, json.dumps(alert_data))
                
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

# WebSocket endpoint for specific video stream
@app.websocket("/ws/video/{video_id}")
async def video_websocket_endpoint(websocket: WebSocket, video_id: str):
    await manager.connect(websocket, video_id)
    try:
        while True:
            # Keep connection alive and handle any incoming messages
            data = await websocket.receive_text()
            # You can handle client messages here if needed
            print(f"Received message from video {video_id}: {data}")
    except WebSocketDisconnect:
        manager.disconnect(websocket, video_id)
    except Exception as e:
        print(f"WebSocket error for video {video_id}: {e}")
        manager.disconnect(websocket, video_id)

# General WebSocket endpoint (for backward compatibility)
@app.websocket("/ws")
async def general_websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket, "general")
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, "general")
    except Exception as e:
        print(f"WebSocket error: {e}")
        manager.disconnect(websocket, "general")

# Get active video streams
@app.get("/active-streams")
async def get_active_streams():
    """Get list of active video streams"""
    streams = []
    for video_id in manager.get_active_streams():
        streams.append({
            "video_id": video_id,
            "connections": manager.get_connection_count(video_id)
        })
    return {"active_streams": streams}

# Get alerts for specific video stream
@app.get("/alerts/{video_id}")
async def get_alerts_for_video(video_id: str):
    """Get alerts for specific video stream"""
    conn = get_db_connection()
    if not conn:
        return {"error": "Database connection failed"}
    
    cursor = conn.cursor(dictionary=True)
    
    try:
        cursor.execute("""
            SELECT sa.*, bp.name, bp.threat_level
            FROM security_alerts sa
            JOIN blacklisted_persons bp ON sa.person_id = bp.id
            WHERE sa.video_id = %s OR (sa.video_id IS NULL AND %s = 'general')
            ORDER BY sa.detection_time DESC
            LIMIT 50
        """, (video_id, video_id))
        
        alerts = cursor.fetchall()
        
        # Convert datetime to string for JSON serialization
        for alert in alerts:
            if alert['detection_time']:
                alert['detection_time'] = alert['detection_time'].isoformat()
            alert['confidence_score'] = float(alert['confidence_score'])
        
        return {"video_id": video_id, "alerts": alerts}
    except Exception as e:
        return {"error": f"Database error: {str(e)}"}
    finally:
        cursor.close()
        conn.close()

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