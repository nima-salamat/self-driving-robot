import cv2
import numpy as np
import os
import argparse
from math import sqrt
from classification import train_and_evaluate, get_label

SIGNS = ["ERROR", "STOP", "TURN LEFT", "TURN RIGHT", "STRAIGHT", "PARK"]

clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))

def clean_images():
    for f in os.listdir('./'):
        if f.endswith('.png'):
            try: os.remove(f)
            except: pass

def get_roi(frame):
 
    height, width = frame.shape[:2]
    top_crop = int(height * 0.1)
    bottom_crop = int(height * 0.8) 
    return top_crop, bottom_crop

def apply_clahe(img):
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l_clahe = clahe.apply(l)
    lab_clahe = cv2.merge((l_clahe, a, b))
    return cv2.cvtColor(lab_clahe, cv2.COLOR_LAB2BGR)

def extract_color_and_edge_mask(img):

    enhanced_img = apply_clahe(img)
    
    hsv = cv2.cvtColor(enhanced_img, cv2.COLOR_BGR2HSV)
    mask_red = cv2.bitwise_or(cv2.inRange(hsv, np.array([0, 70, 50]), np.array([10, 255, 255])), 
                              cv2.inRange(hsv, np.array([170, 70, 50]), np.array([180, 255, 255])))
    mask_blue = cv2.inRange(hsv, np.array([100, 100, 50]), np.array([140, 255, 255]))
    color_mask = cv2.bitwise_or(mask_red, mask_blue)
    color_mask = cv2.dilate(color_mask, np.ones((5,5), np.uint8), iterations=1)

    gray = cv2.cvtColor(enhanced_img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edge_mask = cv2.Canny(blurred, 40, 120)
    
    combined_mask = cv2.bitwise_and(edge_mask, edge_mask, mask=color_mask)
    combined_mask = cv2.morphologyEx(combined_mask, cv2.MORPH_CLOSE, np.ones((3,3), np.uint8))
    
    return combined_mask

def find_robust_signs(image, original_image, mask, model, offset_y, count):
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    best_coordinate = None
    best_sign = None
    best_score = 0
    
    for c in cnts:
        area = cv2.contourArea(c)
        if area < 300: continue
            
        x, y, w, h = cv2.boundingRect(c)
        aspect_ratio = float(w) / h
        if aspect_ratio < 0.6 or aspect_ratio > 1.4: continue

        hull = cv2.convexHull(c)
        hull_area = cv2.contourArea(hull)
        if hull_area == 0: continue
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

def localization(original_image, model, count):
    frame_draw = original_image.copy()
    
    top_y, bottom_y = get_roi(original_image)
    roi_frame = original_image[top_y:bottom_y, :]
    
    binary_mask = extract_color_and_edge_mask(roi_frame)
    
    sign, coordinate = find_robust_signs(roi_frame, original_image, binary_mask, model, top_y, count)
    
    text = ""
    sign_type = -1
    
    if sign is not None and sign.size > 0:
        sign_type = get_label(model, sign)
        if 0 < sign_type < len(SIGNS):
            text = SIGNS[sign_type]
            cv2.imwrite(f"{count}_{text}.png", sign)
            cv2.rectangle(frame_draw, coordinate[0], coordinate[1], (0, 255, 0), 2)
            cv2.putText(frame_draw, text, (coordinate[0][0], coordinate[0][1]-15),
                        cv2.FONT_HERSHEY_PLAIN, 1.5, (0, 0, 255), 2)
        else:
            sign_type = -1

    full_binary = np.zeros(original_image.shape[:2], dtype=np.uint8)
    full_binary[top_y:bottom_y, :] = binary_mask
    
    return coordinate, frame_draw, full_binary, sign_type, text

def main(args):
    clean_images()
    
    model = train_and_evaluate(retrain=args.train)
    if model is None:
        print("[ERROR] Model failed. Exiting...")
        return
        
    vidcap = cv2.VideoCapture(args.file_name)
    fps = vidcap.get(cv2.CAP_PROP_FPS) or 30.0
    out = cv2.VideoWriter('output.avi', cv2.VideoWriter_fourcc(*'XVID'), fps, (1280, 480))

    count, sign_count = 0, 0
    current_sign = None
    coordinates = []

    print("[INFO] Processing video...")
    with open("Output.txt", "w") as file:
        while True:
            success, frame = vidcap.read()
            if not success: break
            frame = cv2.resize(frame, (640,480))

            coordinate, color_image, binary_image, sign_type, text = localization(frame, model, count)
            
            if sign_type > 0 and coordinate is not None:
                if not current_sign or sign_type != current_sign:
                    current_sign = sign_type
                    coordinates.append([count, sign_type, coordinate[0][0], coordinate[0][1], coordinate[1][0], coordinate[1][1]])
                if current_sign: sign_count += 1

            binary_bgr = cv2.cvtColor(binary_image, cv2.COLOR_GRAY2BGR)
            combined_view = np.hstack((color_image, binary_bgr))

            cv2.imshow('Result (Pro-Mode)', combined_view)
            out.write(combined_view)
            
            count += 1
            if cv2.waitKey(1) & 0xFF == ord('q'): break

        file.write(f"{len(coordinates)}\n")
        for pos in coordinates:
            file.write(f"{pos[0]} {pos[1]} {pos[2]} {pos[3]} {pos[4]} {pos[5]}\n")

    vidcap.release()
    out.release()
    cv2.destroyAllWindows()
    print("[INFO] Done!")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--file_name', default="video.mp4", help='Path to the input video file or camera index (0 for default camera)')
    parser.add_argument('--camera', action='store_true')
    parser.add_argument('--train', action='store_true')
    
    args = parser.parse_args()
    if args.camera: args.file_name = 0  
    main(args)
