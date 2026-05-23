class OCRProcessor:
    async def extract_text(self, image_path: str) -> dict:
        return {"text": "", "confidence": 0.0, "source": image_path}
