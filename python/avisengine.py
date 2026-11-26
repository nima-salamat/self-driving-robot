'''
@ 2025, Copyright AVIS Engine
'''

import cv2
import math
import re
import base64
import time
import socket
import zlib
import logging
import numpy as np
import avisengine_utils as utils

__author__ = "Amirmohammad Zarif"
__email__ = "amir@avisengine.com"


logger = logging.getLogger(__name__)

_MAX_AVIS_DECOMPRESSED_BYTES = 64 * 1024 * 1024
_MAX_AVIS_RESPONSE_BYTES = _MAX_AVIS_DECOMPRESSED_BYTES + 8 * 1024 * 1024


def _is_zlib_stream(payload):
    if len(payload) < 2:
        return False
    cmf, flg = payload[0], payload[1]
    return (
        (cmf & 0x0F) == 8
        and (cmf >> 4) <= 7
        and ((cmf << 8) | flg) % 31 == 0
    )


def _decompress_avis_transport(payload):
    """Inflate only standard zlib/gzip streams and bound output size."""
    if payload.startswith(b"\x1f\x8b"):
        encoding, window_bits = "gzip", zlib.MAX_WBITS | 16
    elif _is_zlib_stream(payload):
        encoding, window_bits = "zlib", zlib.MAX_WBITS
    else:
        return payload, "identity", None

    try:
        inflater = zlib.decompressobj(window_bits)
        expanded = inflater.decompress(payload, _MAX_AVIS_DECOMPRESSED_BYTES + 1)
        if len(expanded) > _MAX_AVIS_DECOMPRESSED_BYTES or inflater.unconsumed_tail:
            raise ValueError("decompressed payload exceeds 64 MiB safety limit")
        expanded += inflater.flush()
        if len(expanded) > _MAX_AVIS_DECOMPRESSED_BYTES:
            raise ValueError("decompressed payload exceeds 64 MiB safety limit")
        if not inflater.eof:
            raise ValueError("compressed payload ended before stream completion")
        if inflater.unused_data:
            raise ValueError("compressed payload contains trailing bytes")
        return expanded, encoding, None
    except (zlib.error, ValueError) as exc:
        return None, encoding, str(exc)


def _avis_image_format(payload):
    """Validate a real image header before asking OpenCV to parse the payload."""
    if len(payload) >= 6 and payload.startswith(b"\xff\xd8\xff") and payload.rfind(b"\xff\xd9") >= 3:
        return "jpeg"

    if payload.startswith(b"\x89PNG\r\n\x1a\n") and len(payload) >= 24:
        width = int.from_bytes(payload[16:20], "big")
        height = int.from_bytes(payload[20:24], "big")
        if 0 < width <= 20000 and 0 < height <= 20000:
            return "png"

    if len(payload) >= 30 and payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        declared_size = int.from_bytes(payload[4:8], "little") + 8
        if 30 <= declared_size <= len(payload):
            return "webp"

    if len(payload) >= 8 and (
        payload.startswith(b"II*\x00") or payload.startswith(b"MM\x00*")
    ):
        return "tiff"

    # Validate a complete BMP header; random "BM" bytes are not enough.
    if len(payload) >= 54 and payload.startswith(b"BM"):
        file_size = int.from_bytes(payload[2:6], "little")
        pixel_offset = int.from_bytes(payload[10:14], "little")
        dib_size = int.from_bytes(payload[14:18], "little")
        width = int.from_bytes(payload[18:22], "little", signed=True)
        height = int.from_bytes(payload[22:26], "little", signed=True)
        planes = int.from_bytes(payload[26:28], "little")
        bits_per_pixel = int.from_bytes(payload[28:30], "little")
        compression = int.from_bytes(payload[30:34], "little")
        if (
            dib_size in (40, 52, 56, 108, 124)
            and 0 < width <= 20000
            and 0 < abs(height) <= 20000
            and planes == 1
            and bits_per_pixel in (1, 4, 8, 16, 24, 32)
            and compression in (0, 3, 6)
            and pixel_offset >= 14 + dib_size
            and pixel_offset < len(payload)
            and (file_size == 0 or pixel_offset <= file_size <= len(payload))
        ):
            return "bmp"

    return None


def _find_avis_image_payload(payload):
    """Find an image only at a fully validated format header."""
    image_format = _avis_image_format(payload)
    if image_format is not None:
        return payload, 0, image_format

    # Packet framing can prepend a few bytes before the encoded image. Search
    # only for strong format signatures; every candidate must pass the complete
    # header checks above before it is sent to OpenCV.
    for signature in (
        b"\xff\xd8\xff",
        b"\x89PNG\r\n\x1a\n",
        b"RIFF",
        b"BM",
        b"II*\x00",
        b"MM\x00*",
    ):
        offset = payload.find(signature, 1)
        while offset > 0:
            candidate = payload[offset:]
            image_format = _avis_image_format(candidate)
            if image_format is not None:
                return candidate, offset, image_format
            offset = payload.find(signature, offset + 1)
    return None, 0, None


def _decode_avis_image_payload(payload):
    """Decode verified image payload and expose only safe protocol diagnostics."""
    image_payload, transport, transport_error = _decompress_avis_transport(payload)
    inspected = image_payload if image_payload is not None else payload
    image_candidate, image_offset, image_format = (
        _find_avis_image_payload(inspected) if image_payload is not None else (None, 0, None)
    )
    diagnostic_prefix = image_candidate if image_candidate is not None else inspected
    diagnostics = {
        "image_transport_encoding": transport,
        "transport_payload_prefix_hex": payload[:12].hex(),
        "image_payload_prefix_hex": diagnostic_prefix[:12].hex(),
        "image_payload_offset_bytes": int(image_offset),
        "image_payload_magic": image_format or (
            "gzip" if payload.startswith(b"\x1f\x8b")
            else "zlib" if _is_zlib_stream(payload)
            else "unknown"
        ),
    }
    if transport_error:
        return None, None, diagnostics, "AVIS " + transport + " decompression failed: " + transport_error
    if image_candidate is None:
        return None, None, diagnostics, (
            "Unsupported AVIS image payload signature (prefix "
            + inspected[:12].hex() + ")"
        )

    try:
        frame = cv2.imdecode(
            np.frombuffer(image_candidate, dtype=np.uint8),
            flags=cv2.IMREAD_COLOR,
        )
    except cv2.error as exc:
        return None, None, diagnostics, (
            "OpenCV failed on validated " + image_format + " payload: "
            + str(exc).splitlines()[0]
        )
    if frame is None or not frame.size:
        return None, None, diagnostics, "OpenCV returned an empty " + image_format + " frame"
    diagnostics["image_format"] = image_format
    return frame, image_candidate, diagnostics, None


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
            return True
        except OSError as exc:
            try:
                sock.close()
            finally:
                if self.sock is sock:
                    self.sock = None
            logger.debug("AVIS Engine connection to %s:%s failed: %s", server, port, exc)
            return False

  
    def recvall(self, socket):
        """Read one bounded AVIS response without assuming its payload is text."""
        buffer_size = 131072
        data = bytearray()

        while True:
            part = socket.recv(buffer_size)
            if not part:
                raise ConnectionError("AVIS Engine closed before the <EOF> marker")
            data.extend(part)
            if len(data) > _MAX_AVIS_RESPONSE_BYTES:
                raise ValueError(
                    "AVIS response exceeded the {} MiB safety limit".format(
                        _MAX_AVIS_RESPONSE_BYTES // (1024 * 1024)
                    )
                )
            if utils.KMPSearch(b"<EOF>", data) > -1:
                break

        return bytes(data)

        
    def setDriveCommand(self, steering, speed):
        """Send steering and motor speed together in one AVIS protocol packet."""
        self.steering_value = int(steering)
        self.speed_value = int(speed)
        self.image_mode = 0
        self.sensor_status = 0
        self.updateData()
        self.sock.sendall(self.data_str.encode("utf-8"))
        time.sleep(0.01)

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
        if isinstance(receive, str):
            receive = receive.encode("utf-8", errors="replace")
        else:
            receive = bytes(receive)
        self.last_response_at = time.monotonic()
        image_match = re.search(rb"<image>(.*?)</image>", receive, flags=re.IGNORECASE | re.DOTALL)
        sensor_match = re.search(rb"<sensor>(.*?)</sensor>", receive, flags=re.IGNORECASE | re.DOTALL)
        speed_match = re.search(rb"<speed>(.*?)</speed>", receive, flags=re.IGNORECASE | re.DOTALL)

        info = {
            "response_bytes": len(receive),
            "image_tag": image_match is not None,
            "sensor_tag": sensor_match is not None,
            "speed_tag": speed_match is not None,
            "image_decoded": False,
        }

        # Parse the protocol as bytes. Camera payloads may be binary; decoding
        # the whole TCP response as UTF-8 can corrupt a valid frame or raise
        # UnicodeDecodeError before the image decoder can inspect it.
        image_bytes = None
        decoded = None
        payload_format = "tagged-base64" if image_match is not None else None
        encoded_payload = image_match.group(1) if image_match is not None else b""

        if image_match is None:
            bare_match = re.match(
                rb"\s*([A-Za-z0-9+/=_-]+(?:[ \t\r\n]*[A-Za-z0-9+/=_-]+)*)",
                receive,
            )
            if bare_match is not None:
                encoded_payload = bare_match.group(1)
                payload_format = "leading-base64"

        decode_failure = None
        decode_info = {}
        if payload_format is not None:
            try:
                encoded = re.sub(rb"\s+", b"", encoded_payload).rstrip(b"=")
                if len(encoded) % 4 == 1:
                    raise ValueError("invalid Base64 length")
                encoded += b"=" * ((-len(encoded)) % 4)
                candidate = base64.b64decode(encoded, altchars=b"-_", validate=True)
                decoded, image_bytes, decode_info, decode_failure = _decode_avis_image_payload(candidate)
                info.update(decode_info)
            except (ValueError, base64.binascii.Error) as exc:
                decode_failure = "Base64 image payload could not be decoded: " + str(exc)

        # Some AVIS builds return encoded image bytes directly rather than
        # Base64 text. Accept only a fully validated image signature; arbitrary
        # binary telemetry must never be passed to OpenCV as though it were a frame.
        if decoded is None:
            raw_payload = image_match.group(1) if image_match is not None else receive
            raw_frame, raw_bytes, raw_info, raw_error = _decode_avis_image_payload(raw_payload)
            if raw_frame is not None:
                decoded = raw_frame
                image_bytes = raw_bytes
                decode_info = raw_info
                payload_format = "tagged-binary" if image_match is not None else "raw-binary"
                info.update(decode_info)
            elif payload_format is None:
                decode_info = raw_info
                decode_failure = raw_error
                info.update(decode_info)

        if decoded is not None:
            self.image = decoded
            self.image_sequence += 1
            self.image_received_at = time.monotonic()
            image_format = decode_info.get("image_format", "other")
            info.update({
                "image_decoded": True,
                "image_width": int(decoded.shape[1]),
                "image_height": int(decoded.shape[0]),
                "image_sequence": int(self.image_sequence),
                "encoded_bytes": len(image_bytes),
                "image_payload_format": payload_format,
                "image_format": image_format,
                "image_transport_encoding": decode_info.get("image_transport_encoding", "identity"),
            })
        elif image_match is not None:
            info["decode_error"] = decode_failure or "Tagged <image> payload did not contain a decodable image"
        elif payload_format == "leading-base64":
            info["decode_error"] = decode_failure or "Leading Base64 payload did not contain a decodable image"
        else:
            info["decode_error"] = decode_failure or "AVIS response contained no recognized image payload"

        if sensor_match is not None:
            # Preserve fractional readings instead of silently truncating them.
            sensor_values = re.findall(
                rb"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?",
                sensor_match.group(1),
            )
            parsed_sensors = [float(value) for value in sensor_values]
            self.sensors = [
                int(value) if value.is_integer() else value for value in parsed_sensors
            ]
            info["sensor_values_count"] = len(self.sensors)
        else:
            # Missing telemetry is unknown, not an infinitely clear path.
            self.sensors = [None, None, None]
            info["sensor_values_count"] = 0

        if speed_match is not None:
            try:
                parsed_speed = float(speed_match.group(1).strip())
                if math.isfinite(parsed_speed) and parsed_speed >= 0.0:
                    self.current_speed = parsed_speed
                else:
                    self.current_speed = None
                    info["speed_parse_error"] = True
            except (TypeError, ValueError, OverflowError):
                self.current_speed = None
                info["speed_parse_error"] = True
        else:
            # Missing telemetry is unknown, not a real zero-speed reading.
            self.current_speed = None

        # Do not include encoded frame bytes in logs or diagnostics.
        if image_match is None:
            prefix = receive[:180].strip()
            info["response_prefix_kind"] = (
                "base64-like" if re.fullmatch(rb"[-A-Za-z0-9+/=_\s]+", prefix)
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
    
        
        
