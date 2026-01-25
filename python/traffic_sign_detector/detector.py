import cv2
import numpy as np

from math import sqrt

#Parameter
SIZE = 20
CLASS_NUMBER = 8



SIGNS = [
         "ERROR",
         "TURN LEFT",
         "TURN RIGHT",
         "ONE WAY",
         "TURN RIGHT",
         "TURN LEFT",
         "STRAIGHT",
         "STOP"
]

def deskew(img):
    m = cv2.moments(img)
    if abs(m['mu02']) < 1e-2:
        return img.copy()
    skew = m['mu11']/m['mu02']
    M = np.float32([[1, skew, -0.5*SIZE*skew], [0, 1, 0]])
    img = cv2.warpAffine(img, M, (SIZE, SIZE), flags=cv2.WARP_INVERSE_MAP | cv2.INTER_LINEAR)
    return img

class StatModel(object):
    def load(self, fn):
        self.model = cv2.ml.SVM_load(fn)
    def save(self, fn):
        self.model.save(fn)


class SVM(StatModel):
    def __init__(self, C = 12.5, gamma = 0.50625):
        self.model = cv2.ml.SVM_create()
        self.model.setGamma(gamma)
        self.model.setC(C)
        self.model.setKernel(cv2.ml.SVM_RBF)
        self.model.setType(cv2.ml.SVM_C_SVC)

    def train(self, samples, responses):
        self.model.train(samples, cv2.ml.ROW_SAMPLE, responses)

    def predict(self, samples):

        return self.model.predict(samples)[1].ravel()



def preprocess_simple(data):
    return np.float32(data).reshape(-1, SIZE*SIZE) / 255.0


def get_hog() : 
    winSize = (20,20)
    blockSize = (10,10)
    blockStride = (5,5)
    cellSize = (10,10)
    nbins = 9
    derivAperture = 1
    winSigma = -1.
    histogramNormType = 0
    L2HysThreshold = 0.2
    gammaCorrection = 1
    nlevels = 64
    signedGradient = True

    hog = cv2.HOGDescriptor(winSize,blockSize,blockStride,cellSize,nbins,derivAperture,winSigma,histogramNormType,L2HysThreshold,gammaCorrection,nlevels, signedGradient)

    return hog



def get_model(force_to_train=False):
    svm_file = "traffic_sign_detector/data_svm.dat"

    print(f"Loading existing SVM model from '{svm_file}' ...")
    model = SVM()
    model.load(svm_file)
    return model
    

def constrastLimit(image):
    img_ycrcb = cv2.cvtColor(image, cv2.COLOR_BGR2YCrCb)
    channels = list(cv2.split(img_ycrcb))  # <-- تبدیل tuple به list
    channels[0] = cv2.equalizeHist(channels[0])
    img_ycrcb = cv2.merge(channels)
    return cv2.cvtColor(img_ycrcb, cv2.COLOR_YCrCb2BGR)


def LaplacianOfGaussian(image):
    blurred = cv2.GaussianBlur(image, (3,3), 0)
    gray = cv2.cvtColor(blurred, cv2.COLOR_BGR2GRAY)
    log = cv2.Laplacian(gray, cv2.CV_8U, ksize=3)
    return cv2.convertScaleAbs(log)


def binarization(image):
    _, thresh = cv2.threshold(image, 15, 255, cv2.THRESH_BINARY)
    return thresh


def preprocess_image(image):
    image = constrastLimit(image)
    image = LaplacianOfGaussian(image)
    image = binarization(image)
    return image

# ----------------- Contour / Sign Detection -----------------
def removeSmallComponents(image, threshold):
    nb_components, output, stats, _ = cv2.connectedComponentsWithStats(image, connectivity=8)
    sizes = stats[1:, -1]; nb_components -= 1
    img2 = np.zeros(output.shape, dtype=np.uint8)
    for i in range(nb_components):
        if sizes[i] >= threshold:
            img2[output == i + 1] = 255
    return img2


def findContour(image):
    cnts, _ = cv2.findContours(image, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    return cnts


def contourIsSign(perimeter, centroid, threshold):
    # perimeter: contour (Nx1x2) or list of points
    result = []
    for p in perimeter:
        # support both contour point shapes
        pt = p[0] if isinstance(p, (list, tuple, np.ndarray)) and len(p) > 0 else p
        x = pt[0]
        y = pt[1]
        distance = sqrt((x - centroid[0])**2 + (y - centroid[1])**2)
        result.append(distance)
    if len(result) == 0:
        return (False, 0)
    max_value = max(result)
    if max_value == 0:
        return (False, 0)
    signature = [dist / max_value for dist in result]
    temp = sum((1 - s) for s in signature) / len(signature)
    return (temp < threshold, max_value + 2)


def cropSign(image, coordinate):
    width, height = image.shape[1], image.shape[0]
    top = max(int(coordinate[0][1]), 0)
    bottom = min(int(coordinate[1][1]), height-1)
    left = max(int(coordinate[0][0]), 0)
    right = min(int(coordinate[1][0]), width-1)
    # ensure valid box
    if bottom <= top or right <= left:
        return None
    return image[top:bottom, left:right]


def findLargestSign(image, contours, threshold, distance_threshold):
    """
    Collect candidate signs from contours, return a list of candidates sorted by distance (size proxy).
    Each candidate is a tuple: (distance, sign_image, coordinate)
    """
    candidates = []
    for c in contours:
        M = cv2.moments(c)
        if M.get("m00", 0) == 0:
            continue
        cX = int(M["m10"] / M["m00"])
        cY = int(M["m01"] / M["m00"])
        is_sign, distance = contourIsSign(c, [cX, cY], 1 - threshold)
        if is_sign and distance > distance_threshold:
            pts = c.reshape(-1,2)
            left, top = np.amin(pts, axis=0)
            right, bottom = np.amax(pts, axis=0)
            coordinate = [(int(left)-2, int(top)-2), (int(right)+3, int(bottom)+1)]
            sign = cropSign(image, coordinate)
            if sign is None:
                continue
            candidates.append((distance, sign, coordinate))
    if not candidates:
        return []
    # sort candidates by distance (descending)
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates


def remove_other_color(img):
    frame = cv2.GaussianBlur(img, (3,3), 0)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    # Blue mask
    mask_blue = cv2.inRange(hsv, np.array([100,128,0]), np.array([215,255,255]))
    # White mask
    mask_white = cv2.inRange(hsv, np.array([0,0,128], dtype=np.uint8), np.array([255,255,255], dtype=np.uint8))
    # Black mask
    mask_black = cv2.inRange(hsv, np.array([0,0,0], dtype=np.uint8), np.array([170,150,50], dtype=np.uint8))
    mask = cv2.bitwise_or(cv2.bitwise_or(mask_blue, mask_white), mask_black)
    return mask


def getLabel(model, data):
    gray = cv2.cvtColor(data, cv2.COLOR_BGR2GRAY)
    img = [cv2.resize(gray,(SIZE,SIZE))]
    #print(np.array(img).shape)
    img_deskewed = list(map(deskew, img))
    hog = get_hog()
    hog_descriptors = np.array([hog.compute(img_deskewed[0])])
    hog_descriptors = np.reshape(hog_descriptors, [-1, hog_descriptors.shape[1]])
    return int(model.predict(hog_descriptors)[0])

# ----------------- Localization -----------------
def localization(image, model, min_size_components=300, similitary_contour_with_circle=0.65):
    original_image = image.copy()
    binary_image = preprocess_image(image)
    binary_image = removeSmallComponents(binary_image, min_size_components)
    binary_image = cv2.bitwise_and(binary_image, binary_image, mask=remove_other_color(image))

    contours = findContour(binary_image)
    candidates = findLargestSign(original_image, contours, similitary_contour_with_circle, 15)

    sign = None
    coordinate = None
    sign_type = -1
    text = ""

    # iterate candidates (largest first) and pick the first one that is NOT classified as ERROR (index 0)
    for distance, candidate_sign, coord in candidates:
        try:
            label = getLabel(model, candidate_sign)
        except Exception as e:
            # if classification fails, skip this candidate
            print(f"Classification error: {e}")
            continue
        if label == 0:
            # explicit skip for ERROR class
            continue
        # accept this candidate
        sign = candidate_sign
        coordinate = coord
        sign_type = int(label)
        text = SIGNS[sign_type] if 0 <= sign_type < len(SIGNS) else "UNKNOWN"
        
    
    return coordinate, original_image, sign_type, text



