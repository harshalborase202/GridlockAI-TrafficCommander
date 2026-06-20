# image_enhancer.py
# Enhances vehicle crops to maximize character readability for ANPR OCR.
import cv2
import numpy as np

class ImageEnhancer:
    def __init__(self):
        pass

    def enhance(self, img):
        """
        Enhance BGR image quality for OCR processing.
        Args:
            img: OpenCV BGR image crop.
        Returns:
            numpy.ndarray: Enhanced BGR image crop.
        """
        if img is None or img.size == 0:
            return img

        # 1. Convert to LAB color space to isolate brightness (Luminosity channel)
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)

        # 2. Apply CLAHE (Contrast Limited Adaptive Histogram Equalization)
        # Boosts contrast in local tiles, avoiding global over-exposure
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        cl = clahe.apply(l)

        # 3. Re-merge channels and convert back to standard BGR
        limg = cv2.merge((cl, a, b))
        enhanced = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)

        # 4. Bilateral Filtering for edge-preserving noise reduction
        # This keeps the outlines of letters/numbers sharp while smoothing out road surface noise
        denoised = cv2.bilateralFilter(enhanced, 9, 75, 75)

        # 5. Sharpening using Unsharp Masking
        # Blends original with blurred negative to draw out pixel transition edges
        blurred = cv2.GaussianBlur(denoised, (5, 5), 0)
        sharpened = cv2.addWeighted(denoised, 1.6, blurred, -0.6, 0)

        # 6. Clip bounds safely to prevent overflow corruption
        final_img = np.clip(sharpened, 0, 255).astype(np.uint8)

        return final_img
