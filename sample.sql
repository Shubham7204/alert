-- Blacklisted persons table
CREATE TABLE blacklisted_persons (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(255),
    threat_level ENUM('LOW', 'MEDIUM', 'HIGH') DEFAULT 'MEDIUM',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Security alerts table
CREATE TABLE security_alerts (
    id INT PRIMARY KEY AUTO_INCREMENT,
    person_id INT,
    detection_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    camera_location VARCHAR(255),
    video_id VARCHAR(50),
    confidence_score FLOAT,
    status ENUM('NEW', 'ACKNOWLEDGED', 'RESOLVED') DEFAULT 'NEW',
    FOREIGN KEY (person_id) REFERENCES blacklisted_persons(id)
);

-- Notification queue table (for trigger to populate)
CREATE TABLE notification_queue (
    id INT PRIMARY KEY AUTO_INCREMENT,
    alert_id INT,
    message TEXT,
    video_id VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (alert_id) REFERENCES security_alerts(id)
);

-- Database trigger
DELIMITER $$
CREATE TRIGGER after_alert_insert 
AFTER INSERT ON security_alerts
FOR EACH ROW
BEGIN
    DECLARE person_name VARCHAR(255);
    DECLARE alert_message TEXT;
    
    SELECT name INTO person_name 
    FROM blacklisted_persons 
    WHERE id = NEW.person_id;
    
    SET alert_message = CONCAT(
        'SECURITY ALERT: Dangerous person "', person_name, 
        '" detected at ', NEW.camera_location, 
        ' (Video: ', IFNULL(NEW.video_id, 'Unknown'), ')',
        ' with ', NEW.confidence_score, '% confidence at ', 
        NEW.detection_time
    );
    
    INSERT INTO notification_queue (alert_id, message, video_id) 
    VALUES (NEW.id, alert_message, NEW.video_id);
END$$
DELIMITER ;

-- Insert sample blacklisted persons
INSERT INTO blacklisted_persons (name, threat_level) VALUES 
('John Dangerous', 'HIGH'),
('Jane Suspect', 'MEDIUM'),
('Bob Criminal', 'HIGH');

SELECT * from security_alerts;