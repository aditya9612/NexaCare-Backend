import os
import io
import logging
from PIL import Image

logger = logging.getLogger("nexacare.lab.ocr")

# Lazy initialization of PaddleOCR
_ocr_instance = None

def get_ocr_engine():
    global _ocr_instance
    if _ocr_instance is None:
        try:
            from paddleocr import PaddleOCR
            # Disable angle classifier for much faster CPU inference
            _ocr_instance = PaddleOCR(use_angle_cls=False, lang="en", enable_mkldnn=False)
        except Exception as e:
            logger.error(f"Failed to initialize PaddleOCR: {e}")
            raise RuntimeError(f"OCR engine initialization failed: {e}")
    return _ocr_instance

def sort_ocr_results(ocr_result) -> str:
    """
    Sorts PaddleOCR results to preserve horizontal line and table reading order.
    
    Supports both legacy list-based structure and new dictionary-based structure.
    """
    if not ocr_result:
        return ""
    
    blocks = []
    
    # 1. Handle dictionary-based structure (PaddleX / PaddleOCR 3.x)
    if isinstance(ocr_result[0], dict):
        page = ocr_result[0]
        texts = page.get("rec_texts", [])
        scores = page.get("rec_scores", [])
        polys = page.get("rec_polys", [])
        
        for poly, text, score in zip(polys, texts, scores):
            if hasattr(poly, "tolist"):
                poly_list = poly.tolist()
            else:
                poly_list = poly
            blocks.append([poly_list, (text, score)])
            
    # 2. Handle legacy list-of-lists structure
    elif isinstance(ocr_result[0], list):
        blocks = ocr_result[0]
        
    if not blocks:
        return ""
    
    # Sort blocks primarily by y-coordinate of top-left corner, secondarily by x-coordinate
    sorted_blocks = sorted(blocks, key=lambda b: (b[0][0][1], b[0][0][0]))
    
    lines = []
    current_line = []
    
    for block in sorted_blocks:
        box = block[0]
        text, conf = block[1]
        
        y = box[0][1]
        h = box[2][1] - box[0][1] # height of the bounding box
        
        if not current_line:
            current_line.append(block)
        else:
            prev_box = current_line[-1][0]
            prev_y = prev_box[0][1]
            prev_h = prev_box[2][1] - prev_box[0][1]
            
            # If the difference in y-coordinates is less than 50% of the box height,
            # we consider them to be on the same horizontal line.
            threshold = min(h, prev_h) * 0.5
            if abs(y - prev_y) < threshold:
                current_line.append(block)
            else:
                # Sort the current line by x-coordinate
                current_line.sort(key=lambda b: b[0][0][0])
                lines.append(current_line)
                current_line = [block]
                
    if current_line:
        current_line.sort(key=lambda b: b[0][0][0])
        lines.append(current_line)
        
    # Reassemble the text line by line
    line_texts = []
    for line in lines:
        line_texts.append(" ".join(b[1][0] for b in line))
        
    return "\n".join(line_texts)

def extract_text_from_image_bytes(img_bytes: bytes) -> str:
    """Extract text from raw image bytes using PaddleOCR."""
    import numpy as np
    ocr = get_ocr_engine()
    try:
        img = Image.open(io.BytesIO(img_bytes))
        img_np = np.array(img.convert("RGB"))
        # Call ocr without cls parameter to prevent TypeError on newer versions
        result = ocr.ocr(img_np)
        return sort_ocr_results(result)
    except Exception as e:
        logger.error(f"OCR extraction from image bytes failed: {e}")
        raise RuntimeError(f"OCR failed on image page: {e}")

def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """Extract text from PDF pages by rasterizing them to images and running OCR."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.error("PyMuPDF (fitz) is not installed")
        raise RuntimeError("PyMuPDF is required to process PDF files for OCR")

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if len(doc) == 0:
            raise ValueError("The uploaded PDF is empty")
        
        # 1. Try to extract native text if available (saves time by bypassing OCR)
        native_texts = []
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            text = page.get_text().strip()
            if text:
                native_texts.append(text)
        
        combined_native_text = "\n\n".join(native_texts).strip()
        if len(combined_native_text) > 100:
            logger.info("Extracted digital text natively from PDF. Bypassing PaddleOCR.")
            return combined_native_text

        # 2. Fallback to image-based OCR if no native text is found
        logger.info("No native text found in PDF. Falling back to image-based PaddleOCR.")
        all_pages_text = []
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            # Increase zoom for higher OCR accuracy (e.g. 2x zoom)
            zoom = 2.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("png")
            page_text = extract_text_from_image_bytes(img_bytes)
            all_pages_text.append(f"--- Page {page_num + 1} ---\n{page_text}")
        
        return "\n\n".join(all_pages_text)
    except Exception as e:
        logger.error(f"OCR extraction from PDF bytes failed: {e}")
        raise RuntimeError(f"OCR failed on PDF document: {e}")
