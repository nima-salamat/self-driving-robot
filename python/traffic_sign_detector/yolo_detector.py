import cv2
import numpy as np
import os
import onnxruntime as ort

try:
    from base_config import BASE_DIR
except ImportError:
    BASE_DIR = "." 

class TrafficSignDetector:
    def __init__(self, model_path=None):
        self.SIGNS = ["ERROR", "STOP", "TURN RIGHT", "TURN LEFT", "STRAIGHT", "PARK"]
        self.count = 0 
        
        # Default to the ONNX model
        if model_path is None:
            self.model_file = os.path.join(BASE_DIR, 'assets', 'best.onnx')
        else:
            self.model_file = model_path
            
        print(f"Loading ONNX model from {self.model_file}...")
        
        # Initialize ONNX session (CPU execution only, perfectly safe for Pi)
        self.session = ort.InferenceSession(self.model_file, providers=['CPUExecutionProvider'])
        
        # Get model input shape automatically
        model_inputs = self.session.get_inputs()
        self.input_name = model_inputs[0].name
        input_shape = model_inputs[0].shape 
        
        # Handle dynamic shapes; fallback to 640x640 if standard
        self.input_height = input_shape[2] if isinstance(input_shape[2], int) else 640
        self.input_width = input_shape[3] if isinstance(input_shape[3], int) else 640
        
        os.makedirs("signs_output", exist_ok=True)

    def get_roi(self, frame):
        """Filter out the sky and the car's hood."""
        height, width = frame.shape[:2]
        return int(height * 0.1), int(height * 0.8)

    def letterbox(self, img):
        """
        Manually recreate YOLOv8's image padding technique (letterboxing)
        using NumPy/OpenCV so we don't need PyTorch/Ultralytics installed.
        """
        shape = img.shape[:2]  # [height, width]
        new_shape = (self.input_height, self.input_width)
        
        # Scale ratio (new / old)
        r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])
        
        # Compute padding
        new_unpad = int(round(shape[1] * r)), int(round(shape[0] * r))
        dw, dh = new_shape[1] - new_unpad[0], new_shape[0] - new_unpad[1]  
        
        dw /= 2  # Divide padding equally on both sides
        dh /= 2
        
        if shape[::-1] != new_unpad:  # Resize if needed
            img = cv2.resize(img, new_unpad, interpolation=cv2.INTER_LINEAR)
            
        top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
        left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
        
        # Add gray borders
        img = cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114))
        
        # Format for ONNX: BGR -> RGB -> normalize -> HWC to CHW -> add batch dimension
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img_normalized = img_rgb.astype(np.float32) / 255.0
        img_chw = np.transpose(img_normalized, (2, 0, 1))
        img_batch = np.expand_dims(img_chw, axis=0)
        
        return img_batch, r, dw, dh

    def process_frame(self, original_image, debug_frame=None, confidence_threshold=0.2):
        self.count += 1
        
        top_y, bottom_y = self.get_roi(original_image)
        full_binary = np.zeros(original_image.shape[:2], dtype=np.uint8)
        
        # 1. Preprocess image
        img_tensor, r, dw, dh = self.letterbox(original_image)
        
        # 2. Run pure ONNX inference
        outputs = self.session.run(None, {self.input_name: img_tensor})
        
        # 3. Parse outputs mathematically (ONNX returns shape [1, 4+classes, num_boxes])
        preds = outputs[0]
        preds = np.squeeze(preds, axis=0) # Reshape to [4+classes, num_boxes]
        preds = preds.T # Transpose to [num_boxes, 4+classes] for easier looping
        
        best_coordinate = None
        best_sign_type = -1
        best_score = 0
        best_conf = 0.0
        text = ""
        orig_h, orig_w = original_image.shape[:2]
        
        # 4. Filter and select the largest box
        for row in preds:
            # First 4 values are bounding box: [cx, cy, w, h] on padded image
            # Remaining values are class confidences
            classes_scores = row[4:]
            class_id = np.argmax(classes_scores)
            conf = classes_scores[class_id]
            
            if conf >= confidence_threshold:
                # Re-calculate coordinates back to the unpadded, original image scale
                cx = (row[0] - dw) / r
                cy = (row[1] - dh) / r
                w = row[2] / r
                h = row[3] / r
                
                x1 = int(cx - (w / 2))
                y1 = int(cy - (h / 2))
                x2 = int(cx + (w / 2))
                y2 = int(cy + (h / 2))
                
                # Clamp boundaries so boxes don't overflow image size
                x1 = max(0, x1)
                y1 = max(0, y1)
                x2 = min(orig_w, x2)
                y2 = min(orig_h, y2)
                
                # Check if the sign's center is within our ROI
                center_y = (y1 + y2) // 2
                if center_y < top_y or center_y > bottom_y:
                    continue
                
                # Calculate bounding box area
                area = (x2 - x1) * (y2 - y1)
                
                # If multiple signs exist, focus on the largest one
                if area > best_score:
                    best_score = area
                    best_coordinate = [(x1, y1), (x2, y2)]
                    best_conf = float(conf)
                    
                    # Align YOLO zero-indexed IDs to your 1-indexed class array
                    best_sign_type = int(class_id) + 1

        # 5. Format outputs exactly like the old codebase expects
        if best_sign_type != -1:
            text = f"{self.SIGNS[best_sign_type]}"
            
            # Save the cropped sign
            (x1, y1), (x2, y2) = best_coordinate
            sign_crop = original_image[y1:y2, x1:x2]
            if sign_crop.size > 0:
                cv2.imwrite(f"signs_output/{self.count}_{self.SIGNS[best_sign_type]}.png", sign_crop)
            
            # Draw overlay
            if debug_frame is not None:
                cv2.rectangle(debug_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(debug_frame, text, (x1, y1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2, cv2.LINE_AA)

        if text:
            print(text)
        else:
            print("nothing")

        return {
            "coordinate": best_coordinate,
            "binary_mask": full_binary,
            "sign_type": best_sign_type,
            "text": text,
            "debug_frame": debug_frame 
        }