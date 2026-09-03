import re
import logging

logger = logging.getLogger(__name__)

class FaqAiChunkingService:
    """
    Isolate chunking logic.
    - Approx 500 words per chunk.
    - Approx 50 words overlap.
    - Preserves sentence boundaries.
    """
    
    def __init__(self, target_words: int = 500, overlap_words: int = 50):
        self.target_words = target_words
        self.overlap_words = overlap_words
        
    def chunk_text(self, text: str) -> list[str]:
        if not text:
            return []
            
        # Normalize whitespace while preserving paragraphs
        # Replace multiple spaces with a single space
        text = re.sub(r'[ \t]+', ' ', text)
        # Replace 3+ newlines with 2 newlines to maintain paragraph separation
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = text.strip()
        
        if not text:
            return []

        # Split into sentences. Look for ., ! or ? followed by whitespace.
        # Also split on double newlines to treat paragraph breaks as sentence boundaries.
        sentence_pattern = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9])|\n\n')
        sentences = sentence_pattern.split(text)
        
        # Clean sentences and drop empty
        sentences = [s.strip() for s in sentences if s.strip()]
        
        if not sentences:
            return []
            
        chunks = []
        current_chunk_sentences = []
        current_word_count = 0
        
        for sentence in sentences:
            sentence_words = len(sentence.split())
            
            # If a single sentence is larger than our target, we still add it
            # (we don't break sentences arbitrarily)
            if current_word_count + sentence_words > self.target_words and current_chunk_sentences:
                chunks.append(" ".join(current_chunk_sentences))
                
                # Create overlap for next chunk
                overlap_sentences = []
                overlap_word_count = 0
                for s in reversed(current_chunk_sentences):
                    s_words = len(s.split())
                    if overlap_word_count + s_words <= self.overlap_words:
                        overlap_sentences.insert(0, s)
                        overlap_word_count += s_words
                    else:
                        if not overlap_sentences:
                            # if even the last sentence is too big for overlap, just take it
                            overlap_sentences.insert(0, s)
                        break
                        
                current_chunk_sentences = overlap_sentences
                current_word_count = sum(len(s.split()) for s in current_chunk_sentences)
                
            current_chunk_sentences.append(sentence)
            current_word_count += sentence_words
            
        if current_chunk_sentences:
            chunks.append(" ".join(current_chunk_sentences))
            
        return chunks
