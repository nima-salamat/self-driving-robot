#!/usr/bin/env python3
"""
dataset_collector.py
A simple tool to collect labeled images for autonomous driving training.
Uses the Camera class from camera.py and stores frames in dataset/<label>/
Press keys: 1=left, 2=right, 3=straight, 4=stop, 5=park, q=quit
"""

import os
import sys
import time
import cv2

# Import your Camera class (assumes camera.py is in the same folder)
try:
    from vision.camera import Camera
except ImportError:
    print("ERROR: Could not import Camera from camera.py.")
    print("Make sure camera.py (with the provided Camera class) is in the same directory.")
    sys.exit(1)

# ----- Configuration -----
DATASET_BASE = "dataset"           # Root folder for all collected data
LABEL_MAP = {                      # Key mapping: key -> label string
    ord('1'): "left",
    ord('2'): "right",
    ord('3'): "straight",
    ord('4'): "stop",
    ord('5'): "park",
}
QUIT_KEY = ord('q')                # Press 'q' to exit

# Optional: you can use the resized frame instead of the original full-size frame.
# Set to True to save the resized version (according to camera.py config).
USE_RESIZED = False
# ---------------------------------

def create_folders():
    """Create a subfolder for each label if it doesn't exist."""
    for label in LABEL_MAP.values():
        folder = os.path.join(DATASET_BASE, label)
        os.makedirs(folder, exist_ok=True)
        print(f"Folder ready: {folder}")

def get_next_filename(label_folder):
    """Return a unique filename inside label_folder using a timestamp."""
    timestamp = int(time.time() * 1000)  # milliseconds
    filename = f"{timestamp}.jpg"
    return os.path.join(label_folder, filename)

def overlay_label(frame, label_text):
    """Display the current label (if any) on the frame."""
    if label_text:
        cv2.putText(frame, f"Label: {label_text}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
    return frame

def main():
    # 1. Create output folders
    create_folders()
    
    # 2. Initialise the camera
    print("Initialising camera...")
    try:
        cam = Camera()   # uses your base_config defaults or your custom settings
        print("Camera ready.")
    except Exception as e:
        print(f"Camera initialisation failed: {e}")
        sys.exit(1)
    
    # 3. Main loop
    current_label = None
    print("\nControls:")
    print("  1 - left")
    print("  2 - right")
    print("  3 - straight")
    print("  4 - stop")
    print("  5 - park")
    print("  q - quit")
    print("Press a key to label the current frame and save it.\n")

    while True:
        # Capture frame (original and resized, as defined in your Camera class)
        frame_orig, frame_resized = cam.capture_frame(with_resize=True)
        
        if frame_orig is None:
            print("Warning: empty frame, retrying...")
            time.sleep(0.1)
            continue
        
        # Choose which version to display and save
        frame_to_show = frame_resized if USE_RESIZED else frame_orig
        frame_to_save = frame_orig   # always save full resolution (or change as needed)
        
        # Add label overlay on the displayed image
        display_frame = frame_to_show.copy()
        display_frame = overlay_label(display_frame, current_label)
        
        # Show the frame
        cv2.imshow("Data Collector", display_frame)
        key = cv2.waitKey(1) & 0xFF
        
        # Handle key presses
        if key == QUIT_KEY:
            break
        elif key in LABEL_MAP:
            # Update the label for display and save the current frame
            current_label = LABEL_MAP[key]
            label_folder = os.path.join(DATASET_BASE, current_label)
            save_path = get_next_filename(label_folder)
            
            # Save image
            success = cv2.imwrite(save_path, frame_to_save)
            if success:
                print(f"Saved: {save_path}")
            else:
                print(f"ERROR: Could not write {save_path}")
        # Any other key is ignored; label remains unchanged
    
    # 4. Cleanup
    cv2.destroyAllWindows()
    cam.release()
    print("Collector closed.")

if __name__ == "__main__":
    main()