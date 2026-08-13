import base64
from PIL import Image
import io
import openai

def process_image_upload(image_data: str) -> str:
    """
    Process uploaded image data (base64 encoded) and return a description or analysis.
    Integrated with OpenAI Vision API for advanced analysis.
    """
    try:
        # Decode base64 image data
        if ',' in image_data:
            image_bytes = base64.b64decode(image_data.split(',')[1])  # Remove data URL prefix if present
        else:
            image_bytes = base64.b64decode(image_data)
        image = Image.open(io.BytesIO(image_bytes))
        
        # Resize image if too large (for processing efficiency)
        if image.size[0] > 1024 or image.size[1] > 1024:
            image.thumbnail((1024, 1024))
        
        # Convert to base64 for OpenAI Vision API
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        img_base64 = base64.b64encode(buffer.getvalue()).decode()
        
        # OpenAI Vision API call for image description
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "user", "content": [
                    {"type": "text", "text": "Describe this image in detail, including what's happening, any text, colors, and context. Keep it concise but informative."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_base64}"}}
                ]}
            ],
            max_tokens=150
        )
        description = response.choices[0].message.content.strip()
        
        print(f"[Image] Vision API description: {description}")  # Debug log
        return description
        
    except Exception as e:
        print(f"[Image] Error processing image: {str(e)}")  # Debug log
        return f"Error processing image: {str(e)}. (Basic info: {image.size if 'image' in locals() else 'Unknown'} pixels)"