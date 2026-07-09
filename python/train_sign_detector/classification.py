import cv2
import numpy as np
import os

MODEL_FILE = 'svm_model.xml'
DATASET_PATH = './dataset'

winSize = (32, 32)
blockSize = (16, 16)
blockStride = (8, 8)
cellSize = (8, 8)
nbins = 9
hog = cv2.HOGDescriptor(winSize, blockSize, blockStride, cellSize, nbins, 1, 4.0, 0, 0.2, 0, 64)

def extract_features(image):
    img_resized = cv2.resize(image, (32, 32))
    
    hsv = cv2.cvtColor(img_resized, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [16, 16], [0, 180, 0, 256])
    cv2.normalize(hist, hist)
    color_features = hist.flatten()
    
    gray = cv2.cvtColor(img_resized, cv2.COLOR_BGR2GRAY)
    hog_features = hog.compute(gray).flatten()
    
    combined_features = np.concatenate((color_features, hog_features))
    return combined_features.astype(np.float32)

def load_dataset(dataset_path):
    print("[INFO] Loading dataset...")
    labels, features_list = [], []
    
    if not os.path.exists(dataset_path):
        return None, None

    for label_dir in os.listdir(dataset_path):
        dir_path = os.path.join(dataset_path, label_dir)
        if not os.path.isdir(dir_path): continue
            
        try: label = int(label_dir)
        except: continue
            
        for img_name in os.listdir(dir_path):
            img_path = os.path.join(dir_path, img_name)
            img = cv2.imread(img_path)
            if img is not None:
                features_list.append(extract_features(img))
                labels.append(label)

    if not features_list: return None, None
    return np.array(features_list), np.array(labels, dtype=np.int32)

def train_and_evaluate(retrain=False):
    svm = cv2.ml.SVM_create()
    
    if not retrain and os.path.exists(MODEL_FILE):
        print("[INFO] Loading Model...")
        return svm.load(MODEL_FILE)

    print("[INFO] Training new Model (This might take a moment to find best thresholds)...")
    features, labels = load_dataset(DATASET_PATH)
    
    if features is None:
        print("[ERROR] No dataset found.")
        return svm.load(MODEL_FILE) if os.path.exists(MODEL_FILE) else None

    svm.setType(cv2.ml.SVM_C_SVC)
    svm.setKernel(cv2.ml.SVM_RBF)
    
    svm.trainAuto(features, cv2.ml.ROW_SAMPLE, labels)

    svm.save(MODEL_FILE)
    
    print(f"[SUCCESS] Model trained optimally! C: {svm.getC():.2f}, Gamma: {svm.getGamma():.4f}")
    
    return svm

def get_label(model, image):
    if model is None or image is None or image.size == 0: return 0 
    try:
        features = extract_features(image)
        _, result = model.predict(np.array([features]))
        return int(result[0][0])
    except:
        return 0 

if __name__ == "__main__":
    train_and_evaluate(retrain=True)