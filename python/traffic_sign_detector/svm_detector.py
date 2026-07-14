import cv2
import numpy as np
import os

try:
    from base_config import BASE_DIR
except ImportError:
    BASE_DIR = "." 

class TrafficSignDetector:
    def __init__(self, model_path=None):
        self.SIGNS = ["ERROR", "STOP", "TURN RIGHT", "TURN LEFT", "STRAIGHT", "PARK"]
        self.count = 0 
        
        self.clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        
        winSize = (32, 32)
        blockSize = (16, 16)
        blockStride = (8, 8)
        cellSize = (8, 8)
        nbins = 9
        
        try:
            self.hog = cv2.HOGDescriptor(winSize, blockSize, blockStride, cellSize, nbins, 1, 4.0, 0, 0.2, 0, 64)
        except (TypeError, AttributeError):
            self.hog = cv2.HOGDescriptor(winSize, blockSize, blockStride, cellSize, nbins)
        
        if model_path is None:
            self.model_file = os.path.join(BASE_DIR, 'assets', 'svm_model.xml')
        else:
            self.model_file = model_path
            
        self.model = cv2.ml.RTrees_create()
        
        if os.path.exists(self.model_file):
            self.model = self.model.load(self.model_file)
        else:
            alt_path = os.path.join(BASE_DIR, 'rf_model.xml')
            if os.path.exists(alt_path):
                self.model = self.model.load(alt_path)
            else:
                print(f"Warning: Model file not found at {self.model_file} or {alt_path}")

    def extract_features(self, image):
        img_resized = cv2.resize(image, (32, 32))
        
        hsv = cv2.cvtColor(img_resized, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [16, 16], [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        color_features = hist.flatten()
        
        gray = cv2.cvtColor(img_resized, cv2.COLOR_BGR2GRAY)
        hog_features = self.hog.compute(gray).flatten()
        
        combined_features = np.concatenate((color_features, hog_features))
        return combined_features.astype(np.float32)

    def get_label(self, image):
        if self.model is None or image is None or image.size == 0: 
            return 0 
        try:
            features = self.extract_features(image)
            _, result = self.model.predict(np.array([features]))
            return int(result[0][0])
        except Exception as e:
            print(f"Prediction error: {e}")
            return 0 

    def get_roi(self, frame):
        height, width = frame.shape[:2]
        top_crop = int(height * 0.1)  
        bottom_crop = int(height * 0.8) 
        return top_crop, bottom_crop

    def apply_clahe(self, img):
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        l_clahe = self.clahe.apply(l)
        lab_clahe = cv2.merge((l_clahe, a, b))
        return cv2.cvtColor(lab_clahe, cv2.COLOR_LAB2BGR)

    def extract_color_and_edge_mask(self, img):
        enhanced_img = self.apply_clahe(img)
        
        hsv = cv2.cvtColor(enhanced_img, cv2.COLOR_BGR2HSV)
        mask_red = cv2.bitwise_or(
            cv2.inRange(hsv, np.array([0, 70, 50]), np.array([10, 255, 255])), 
            cv2.inRange(hsv, np.array([170, 70, 50]), np.array([180, 255, 255]))
        )
        mask_blue = cv2.inRange(hsv, np.array([100, 100, 50]), np.array([140, 255, 255]))
        color_mask = cv2.bitwise_or(mask_red, mask_blue)
        color_mask = cv2.dilate(color_mask, np.ones((5,5), np.uint8), iterations=1)

        gray = cv2.cvtColor(enhanced_img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edge_mask = cv2.Canny(blurred, 40, 120)
        
        combined_mask = cv2.bitwise_and(edge_mask, edge_mask, mask=color_mask)
        combined_mask = cv2.morphologyEx(combined_mask, cv2.MORPH_CLOSE, np.ones((3,3), np.uint8))
        
        return combined_mask

    def find_robust_signs(self, image, original_image, mask, offset_y):
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        best_coordinate = None
        best_sign = None
        best_score = 0
        
        for c in cnts:
            area = cv2.contourArea(c)
            if area < 300: 
                continue 
                
            x, y, w, h = cv2.boundingRect(c)
            aspect_ratio = float(w) / h
            if aspect_ratio < 0.6 or aspect_ratio > 1.4: 
                continue

            hull = cv2.convexHull(c)
            hull_area = cv2.contourArea(hull)
            if hull_area == 0: 
                continue
            solidity = float(area) / hull_area
            
            if solidity > 0.7 and area > best_score:
                best_score = area
                pad = 5
                left, top = max(0, x-pad), max(0, y-pad)
                right, bottom = min(image.shape[1], x+w+pad), min(image.shape[0], y+h+pad)
                
                real_top = top + offset_y
                real_bottom = bottom + offset_y
                
                best_coordinate = [(left, real_top), (right, real_bottom)]
                best_sign = original_image[real_top:real_bottom, left:right]

        return best_sign, best_coordinate

    def process_frame(self, original_image, debug_frame=None):
        self.count += 1
        
        top_y, bottom_y = self.get_roi(original_image)
        roi_frame = original_image[top_y:bottom_y, :]
        
        binary_mask = self.extract_color_and_edge_mask(roi_frame)
        
        sign, coordinate = self.find_robust_signs(roi_frame, original_image, binary_mask, top_y)
        
        text = ""
        sign_type = -1
        
        if sign is not None and sign.size > 0:
            sign_type = self.get_label(sign)
            
            if 0 < sign_type < len(self.SIGNS):
                text = self.SIGNS[sign_type]
                
                output_dir = "signs_output"
                if not os.path.exists(output_dir):
                    os.makedirs(output_dir)
                    
                cv2.imwrite(f"{output_dir}/{self.count}_{text}.png", sign)
                
                if debug_frame is not None:
                    cv2.rectangle(debug_frame, coordinate[0], coordinate[1], (0, 255, 0), 2)
                    
                    cv2.putText(debug_frame, text, (coordinate[0][0], coordinate[0][1]-10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2, cv2.LINE_AA)
            else:
                sign_type = -1

        full_binary = np.zeros(original_image.shape[:2], dtype=np.uint8)
        full_binary[top_y:bottom_y, :] = binary_mask
        print(text)
        return {
            "coordinate": coordinate,
            "binary_mask": full_binary,
            "sign_type": sign_type,
            "text": text,
            "debug_frame": debug_frame 
        }