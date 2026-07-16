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
        
        # Handle dynamic shapes; fallback to 416 based on your working test code
        self.input_height = input_shape[2] if isinstance(input_shape[2], int) else 416
        self.input_width = input_shape[3] if isinstance(input_shape[3], int) else 416
        
        os.makedirs("signs_output", exist_ok=True)

    def get_roi(self, frame):
        """Filter out the sky and the car's hood."""
        height, width = frame.shape[:2]
        return int(height * 0.1), int(height * 0.8)

    def preprocess(self, img):
        """
        Resize maintaining aspect ratio and pad with black pixels (letterbox).
        Exactly matches the logic from the working YOLOv8 test code.
        """
        h0, w0 = img.shape[:2]
        
        # Calculate scale to fit within the model's required input size
        scale = min(self.input_width / w0, self.input_height / h0)
        
        nw = int(w0 * scale)
        nh = int(h0 * scale)
        
        # Resize image
        resized = cv2.resize(img, (nw, nh))
        
        # Create padded canvas (0 for black padding as requested)
        # Note: If accuracy drops, change 0 to 114 (YOLO default gray padding)
        canvas = np.full((self.input_height, self.input_width, 3), 0, dtype=np.uint8)
        
        # Calculate padding dimensions
        dw = (self.input_width - nw) // 2
        dh = (self.input_height - nh) // 2
        
        # Place resized image into the center of the canvas
        canvas[dh:dh+nh, dw:dw+nw] = resized
        
        # Format for ONNX: BGR -> RGB -> normalize -> HWC to CHW -> add batch dimension
        img_rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
        img_normalized = img_rgb.astype(np.float32) / 255.0
        img_chw = np.transpose(img_normalized, (2, 0, 1))
        img_batch = np.expand_dims(img_chw, axis=0)
        
        return img_batch, scale, dw, dh

    def process_frame(self, original_image, debug_frame=None, confidence_threshold=0.25):
        self.count += 1
        
        top_y, bottom_y = self.get_roi(original_image)
        full_binary = np.zeros(original_image.shape[:2], dtype=np.uint8)
        
        # 1. Preprocess image (Resize and Black Padding)
        img_tensor, scale, dw, dh = self.preprocess(original_image)
        
        # 2. Run pure ONNX inference
        outputs = self.session.run(None, {self.input_name: img_tensor})
        
        # 3. Parse outputs mathematically
        preds = outputs[0]
        preds = np.squeeze(preds) 
        
        # Handle YOLOv8 shape (transpose if needed)
        if preds.shape[0] == 4 + (len(self.SIGNS) - 1): # adjust based on number of classes
            preds = preds.T 
            
        boxes = []
        scores = []
        class_ids = []
        
        # 4. Extract all valid boxes first
        for row in preds:
            classes_scores = row[4:]
            class_id = np.argmax(classes_scores)
            conf = classes_scores[class_id]
            
            if conf >= confidence_threshold:
                cx, cy, w, h = row[:4]
                
                # Convert center x,y to top-left x,y
                x = cx - w / 2
                y = cy - h / 2
                
                # Remove letterbox padding and scale back to original image size
                x = (x - dw) / scale
                y = (y - dh) / scale
                w = w / scale
                h = h / scale
                
                boxes.append([int(x), int(y), int(w), int(h)])
                scores.append(float(conf))
                class_ids.append(class_id)
                
        # 5. Apply Non-Maximum Suppression (Crucial for YOLOv8)
        indices = cv2.dnn.NMSBoxes(boxes, scores, confidence_threshold, 0.45)
        
        best_coordinate = None
        best_sign_type = -1
        best_score = 0
        best_conf = 0.0
        text = ""
        orig_h, orig_w = original_image.shape[:2]
        
        # 6. Filter by ROI and select the largest box among the valid NMS results
        if len(indices) > 0:
            for i in indices.flatten():
                x, y, w, h = boxes[i]
                conf = scores[i]
                class_id = class_ids[i]
                
                x1 = max(0, x)
                y1 = max(0, y)
                x2 = min(orig_w, x + w)
                y2 = min(orig_h, y + h)
                
                # Check if the sign's center is within our ROI
                center_y = (y1 + y2) // 2
                if center_y < top_y or center_y > bottom_y:
                    continue
                    
                # Calculate bounding box area
                area = (x2 - x1) * (y2 - y1)
                
                # Focus on the largest sign
                if area > best_score:
                    best_score = area
                    best_coordinate = [(x1, y1), (x2, y2)]
                    best_conf = conf
                    
                    # Align YOLO zero-indexed IDs to your 1-indexed class array
                    best_sign_type = int(class_id) + 1

        # 7. Format outputs exactly like the old codebase expects
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
                
                # Background for text to make it readable
                (text_w, text_h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
                cv2.rectangle(debug_frame, (x1, y1 - text_h - 10), (x1 + text_w, y1), (0, 255, 0), -1)
                cv2.putText(debug_frame, text, (x1, y1 - 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2, cv2.LINE_AA)

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
