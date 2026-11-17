'''
@ 2025, Copyright AVIS Engine
'''

import cv2
import re
import base64
import time
import socket
import numpy as np
import avisengine_utils as utils

__author__ = "Amirmohammad Zarif"
__email__ = "amir@avisengine.com"


class Car():
    '''
    AVIS Engine Main Car class
    
    Attributes
    ----------

    Public:
        steering_value
        speed_value
        sensor_status
        image_mode
        get_Speed
        data_arr
        data_str
        sock
        image
        sensors
        current_speed
        sensor_angle
    '''

    def __init__(self):
        # Keep each robot runtime isolated; the upstream API stores its socket
        # at class scope, which would otherwise share a closed socket on restart.
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.timeout = 5.0
        self.steering_value = 0
        self.speed_value = 0
        self.sensor_status = 1
        self.image_mode = 1
        self.get_Speed = 1
        self.sensor_angle = 30
        self.data_arr = [self.speed_value, self.steering_value, self.image_mode,
                         self.sensor_status, self.get_Speed, self.sensor_angle]
        self.data_str = self._data_format.format(*self.data_arr)
        self.image = None
        self.sensors = None
        self.current_speed = None
        # This generation advances only when a valid fresh image is decoded.
        self.image_sequence = 0
        self.image_received_at = None
        self.last_response_at = None
        self.last_response_info = {}

    #Attributes to kind of replicate a Pub-sub pattern messaging to request data  
    steering_value = 0
    speed_value = 0
    sensor_status = 1
    image_mode = 1
    get_Speed = 1
    sensor_angle = 30
    
    sock = None

    #Data format for request
    data_arr = [speed_value, steering_value, image_mode, sensor_status, get_Speed, sensor_angle]
    _data_format = "Speed:{},Steering:{},ImageStatus:{},SensorStatus:{},GetSpeed:{},SensorAngle:{}"
    data_str = _data_format.format(data_arr[0], data_arr[1], data_arr[2], data_arr[3], data_arr[4], data_arr[5])
    
    image = None
    sensors = None
    current_speed = None

    def connect(self,server,port):
        '''
        Connecting to the simulator (server)
        '''
        try:
            self.sock.settimeout(float(getattr(self, "timeout", 5.0)))
            self.sock.connect((server, port))
            
            print("connected to ", server, port)
            return True
        except:
            print("Failed to connect to ", server, port)
            return False

  
    def recvall(self, socket):
        '''
        Function to receive all the data chunks
        '''
        BUFFER_SIZE = 131072  # Increased buffer size for better performance
        data = bytearray()  # Use a bytearray for better performance

        while True:
            part = socket.recv(BUFFER_SIZE)
            if not part:
                raise ConnectionError("AVIS Engine closed before the <EOF> marker")
            data.extend(part)

            # Use KMP search to find the <EOF>, KMPSearch() returns -1 if the pattern was not found
            # It is 9 times faster than the simple python search
            if utils.KMPSearch(b"<EOF>", data) > -1:  # Convert "<EOF>" to bytes              
                break

        return data.decode("utf-8")

        
    def setSteering(self,steering):
        '''
        Setting the steering of the car
        
        Parameters
        ----------
            steering : int
                Steering value in degree
        '''
        self.steering_value = steering
        self.image_mode = 0
        self.sensor_status = 0
        self.updateData()
        self.sock.sendall(self.data_str.encode("utf-8"))
        time.sleep(0.01)

    def setSpeed(self,speed):
        '''
        Setting the speed of the car
        
        Parameters
        ----------
            speed : int
        '''
        self.speed_value = speed
        self.image_mode = 0
        self.sensor_status = 0
        self.updateData()
        self.sock.sendall(self.data_str.encode("utf-8"))
        time.sleep(0.01)

    def setSensorAngle(self, angle):
        '''
        Setting the angle between each sensor ray
        
        Parameters
        ----------
            angle : int
                In degrees
        '''

        self.image_mode = 0
        self.sensor_status = 0
        self.sensor_angle = angle
        self.updateData()
        self.sock.sendall(self.data_str.encode("utf-8"))
        
    def getData(self):
        """Request one AVIS sample and retain explicit camera/protocol diagnostics.

        AVIS may return sensor data without an image (for example while the
        simulator is resetting). Never leave that condition indistinguishable
        from a socket failure, and never let a stale image masquerade as fresh.
        """
        self.image_mode = 1
        self.sensor_status = 1
        self.updateData()
        self.sock.sendall(self.data_str.encode("utf-8"))

        receive = self.recvall(self.sock)
        self.last_response_at = time.monotonic()
        image_match = re.search(r"<image>(.*?)</image>", receive, flags=re.IGNORECASE | re.DOTALL)
        sensor_match = re.search(r"<sensor>(.*?)</sensor>", receive, flags=re.IGNORECASE | re.DOTALL)
        speed_match = re.search(r"<speed>(.*?)</speed>", receive, flags=re.IGNORECASE | re.DOTALL)

        info = {
            "response_bytes": len(receive.encode("utf-8", errors="replace")),
            "image_tag": image_match is not None,
            "sensor_tag": sensor_match is not None,
            "speed_tag": speed_match is not None,
            "image_decoded": False,
        }

        # The legacy AVIS TCP protocol carries camera data explicitly in
        # <image>...</image>. Do not guess that arbitrary response text is an
        # image: sensor/status payloads can contain long Base64-looking fields.
        image_bytes = None
        decoded = None
        if image_match is not None:
            try:
                candidate = base64.b64decode(
                    re.sub(r"\s+", "", image_match.group(1)),
                    validate=True,
                )
                start = candidate.find(b"\xff\xd8")
                end = candidate.rfind(b"\xff\xd9")
                if start >= 0 and end > start:
                    image_bytes = candidate[start:end + 2]
                    image_array = np.frombuffer(image_bytes, dtype=np.uint8)
                    decoded = cv2.imdecode(image_array, flags=cv2.IMREAD_COLOR)
                    if decoded is None or not decoded.size:
                        decoded = None
            except (ValueError, base64.binascii.Error):
                decoded = None

        if decoded is not None:
            self.image = decoded
            self.image_sequence += 1
            self.image_received_at = time.monotonic()
            info.update({
                "image_decoded": True,
                "image_width": int(decoded.shape[1]),
                "image_height": int(decoded.shape[0]),
                "image_sequence": int(self.image_sequence),
                "encoded_bytes": len(image_bytes),
                "image_payload_format": "tagged" if image_match is not None else "bare-base64-jpeg",
            })
        elif image_match is not None:
            info["decode_error"] = "Tagged image payload did not contain a decodable JPEG"
        else:
            info["decode_error"] = "Legacy AVIS response did not contain an <image> tag"

        if sensor_match is not None:
            sensor_values = re.findall(r"-?\d+", sensor_match.group(1))
            self.sensors = list(map(int, sensor_values))
        else:
            self.sensors = [1500, 1500, 1500]

        if speed_match is not None:
            try:
                self.current_speed = int(float(speed_match.group(1).strip()))
            except (TypeError, ValueError, OverflowError):
                self.current_speed = 0
                info["speed_parse_error"] = True
        else:
            self.current_speed = 0

        # Do not include the base64 image in logs or diagnostics.
        if image_match is None:
            prefix = receive[:180].strip()
            info["response_prefix_kind"] = (
                "base64-like" if re.fullmatch(r"[A-Za-z0-9+/=\s]+", prefix)
                else "mixed-protocol-data" if prefix else "empty"
            )
        self.last_response_info = info
        return bool(info["image_decoded"])

    def getImage(self):
        '''
        Returns the image from the camera
        '''
        return self.image

    def getSensors(self):
        '''
        Returns the sensor data
            A List: 
                [Left Sensor: int, Middle Sensor: int, Right Sensor: int]
        '''
        return self.sensors
    
    def getSpeed(self):
        '''
        Returns the speed of the car
        '''
        return self.current_speed
    
    def updateData(self):
        '''
        Updating the request data array and data string
        '''
        data = [self.speed_value,self.steering_value,self.image_mode,self.sensor_status,self.get_Speed, self.sensor_angle]
        self.data_str = self._data_format.format(data[0], data[1], data[2], data[3], data[4], data[5])
        
    def stop(self):
        """Best-effort stop and close; safe after a server-side reset."""
        sock = getattr(self, "sock", None)
        if sock is None:
            return
        try:
            if not getattr(sock, "_closed", False):
                try:
                    self.setSpeed(0)
                    self.setSteering(0)
                    sock.sendall(b"stop")
                except Exception:
                    pass
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def __del__(self):
        try:
            self.stop()
        except Exception:
            pass
    
        
        
