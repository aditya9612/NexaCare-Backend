import os
import numpy as np
from PIL import Image
from app.utils.ocr import get_ocr_engine, sort_ocr_results

class OCRProcessor:
    """OCR Processor for text extraction from images reusing centralized OCR utilities."""
    
    async def extract_text(self, image_path: str) -> dict:
        """
        Extract text from an image file.
        
        Args:
            image_path: Path to the image file.
            
        Returns:
            Dictionary with extracted text, average confidence, and source path.
        """
        if not os.path.exists(image_path):
            return {
                "text": "",
                "confidence": 0.0,
                "source": image_path,
                "error": "File not found"
            }
            
        try:
            # Get the shared/centralized OCR engine
            ocr = get_ocr_engine()
            
            # Open the image and convert to RGB numpy array
            img = Image.open(image_path)
            img_np = np.array(img.convert("RGB"))
            
            # Run OCR on the image
            result = ocr.ocr(img_np)
            text = sort_ocr_results(result)
            
            # Calculate average confidence score
            confidence = 0.0
            if result and isinstance(result, list) and len(result) > 0:
                if isinstance(result[0], dict):
                    scores = result[0].get("rec_scores", [])
                    confidence = sum(scores) / len(scores) if scores else 0.0
                elif isinstance(result[0], list):
                    scores = [line[1][1] for line in result[0]]
                    confidence = sum(scores) / len(scores) if scores else 0.0
                    
            return {
                "text": text,
                "confidence": round(float(confidence), 4),
                "source": image_path
            }
        except Exception as e:
            return {
                "text": "",
                "confidence": 0.0,
                "source": image_path,
                "error": str(e)
            }
