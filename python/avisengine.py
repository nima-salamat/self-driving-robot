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
        # Create the TCP socket in connect(), never reuse a closed socket.
        self.sock = None
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

    def connect(self, server, port):
        """Open a brand-new TCP socket for this connection attempt."""
        self.disconnect(send_stop=False)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock = sock
        try:
            sock.settimeout(float(getattr(self, "timeout", 5.0)))
            sock.connect((server, int(port)))
            print("connected to ", server, port)
            return True
        except OSError:
            try:
                sock.close()
            finally:
                if self.sock is sock:
                    self.sock = None
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

        # AVIS servers use more than one response format. Newer versions wrap
        # camera data in <image> tags; legacy versions send a leading Base64
        # image followed by <sensor>/<speed>/<EOF> metadata. Decode the actual
        # supported image format rather than assuming every frame is a tagged
        # JPEG. OpenCV's decoder is the final authority; telemetry-like Base64
        # is not promoted unless it contains a real decodable image.
        image_bytes = None
        decoded = None
        payload_format = "tagged-base64" if image_match is not None else None
        encoded_payload = image_match.group(1) if image_match is not None else ""

        if image_match is None:
            bare_match = re.match(r"\s*([A-Za-z0-9+/=_-]+(?:[ \t\r\n]*[A-Za-z0-9+/=_-]+)*)", receive)
            if bare_match is not None:
                encoded_payload = bare_match.group(1)
                payload_format = "leading-base64"

        decode_failure = None
        if payload_format is not None:
            try:
                encoded = re.sub(r"\s+", "", encoded_payload)
                # AVIS versions may emit URL-safe or unpadded Base64. Normalize
                # padding but keep strict validation of the encoded alphabet.
                encoded = encoded.rstrip("=")
                if len(encoded) % 4 == 1:
                    raise ValueError("invalid Base64 length")
                encoded += "=" * ((-len(encoded)) % 4)
                candidate = base64.b64decode(encoded, altchars=b"-_", validate=True)

                # Try the complete decoded buffer first, then known image
                # signatures for servers which prepend a small transport header.
                candidates = [candidate]
                for signature in (
                    b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n",
                    b"RIFF", b"BM", b"II*\x00", b"MM\x00*",
                ):
                    offset = candidate.find(signature)
                    if offset > 0:
                        candidates.append(candidate[offset:])

                for image_candidate in candidates:
                    attempt = cv2.imdecode(
                        np.frombuffer(image_candidate, dtype=np.uint8),
                        flags=cv2.IMREAD_COLOR,
                    )
                    if attempt is not None and attempt.size:
                        decoded = attempt
                        image_bytes = image_candidate
                        break

                if decoded is None:
                    decode_failure = (
                        "Base64 decoded to " + str(len(candidate))
                        + " bytes, but OpenCV could not decode a supported image"
                    )
            except (ValueError, base64.binascii.Error) as exc:
                decode_failure = "Base64 image payload could not be decoded: " + str(exc)

        if decoded is not None:
            self.image = decoded
            self.image_sequence += 1
            self.image_received_at = time.monotonic()
            image_format = (
                "jpeg" if image_bytes.startswith(b"\xff\xd8")
                else "png" if image_bytes.startswith(b"\x89PNG")
                else "webp" if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP"
                else "bmp" if image_bytes.startswith(b"BM")
                else "other"
            )
            info.update({
                "image_decoded": True,
                "image_width": int(decoded.shape[1]),
                "image_height": int(decoded.shape[0]),
                "image_sequence": int(self.image_sequence),
                "encoded_bytes": len(image_bytes),
                "image_payload_format": payload_format,
                "image_format": image_format,
            })
        elif image_match is not None:
            info["decode_error"] = decode_failure or "Tagged <image> payload did not contain a decodable image"
        elif payload_format == "leading-base64":
            info["decode_error"] = decode_failure or "Leading Base64 payload did not contain a decodable image"
        else:
            info["decode_error"] = "AVIS response contained no <image> tag or leading Base64 image payload"

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
                "base64-like" if re.fullmatch(r"[-A-Za-z0-9+/=_\s]+", prefix)
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
        
    def disconnect(self, send_stop=True):
        """Release the AVIS server-side client slot and close this socket once.

        The legacy Engine protocol uses the literal stop token to end a client
        session. A plain TCP close after a timed-out request can leave older
        Engine builds holding the previous session open.
        """
        sock = getattr(self, "sock", None)
        self.sock = None
        if sock is None:
            return
        try:
            if send_stop and sock.fileno() >= 0:
                try:
                    sock.sendall(b"stop")
                except OSError:
                    pass
        finally:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    def stop(self):
        """Best-effort actuator stop followed by protocol-level disconnect."""
        sock = getattr(self, "sock", None)
        if sock is None:
            return
        try:
            if sock.fileno() >= 0:
                try:
                    self.setSpeed(0)
                    self.setSteering(0)
                except OSError:
                    pass
        finally:
            self.disconnect(send_stop=True)

    def __del__(self):
        # Destruction must not send actuator commands or issue a second stop.
        try:
            self.disconnect(send_stop=False)
        except Exception:
            pass
    
        
        
