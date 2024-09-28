import os
import json
import base64
from typing import List
from fastapi import FastAPI, File, UploadFile, Query
from fastapi.responses import JSONResponse
import requests
from PIL import Image
import io

app = FastAPI()

COMFYUI_URL = "http://localhost:8188"
WORKFLOW_PATH = "workflow\impaint_workflow.json"

ALLOWED_SIZES = [460, 500, 600, 640, 720, 1000]

def load_workflow():
    with open(WORKFLOW_PATH, 'r') as file:
        return json.load(file)

def send_image_to_comfyui(image: Image.Image, node_id: int):
    buffered = io.BytesIO()
    image.save(buffered, format="PNG")
    img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
    
    payload = {
        "image": img_base64,
        "node_id": node_id
    }
    response = requests.post(f"{COMFYUI_URL}/upload/image", json=payload)
    return response.json()['name']

def run_workflow(workflow: dict, images: List[str]):
    workflow['nodes']['140']['inputs']['image'] = images[0]  # 원본 이미지
    workflow['nodes']['218']['inputs']['image'] = images[1]  # 대체 이미지
    response = requests.post(f"{COMFYUI_URL}/execute", json={"workflow": workflow})
    return response.json()['run_id']

def get_output_image(run_id: str):
    while True:
        response = requests.get(f"{COMFYUI_URL}/status")
        data = response.json()
        if run_id in data:
            if data[run_id]['status'] == 'completed':
                output_images = data[run_id]['output_images']
                if output_images:
                    image_url = f"{COMFYUI_URL}/view?filename={output_images[0]}"
                    return requests.get(image_url).content
        else:
            return None

def resize_image(image: bytes, size: int) -> bytes:
    img = Image.open(io.BytesIO(image))
    aspect_ratio = img.width / img.height
    new_width = size
    new_height = int(size / aspect_ratio)
    img_resized = img.resize((new_width, new_height), Image.LANCZOS)
    buffered = io.BytesIO()
    img_resized.save(buffered, format="PNG")
    return buffered.getvalue()

@app.post("/process_images/")
async def process_images(
    original: UploadFile = File(...), 
    replacement: UploadFile = File(...),
    size: int = Query(640, description="Output image size in pixels")
):
    if size not in ALLOWED_SIZES:
        return JSONResponse(content={"error": f"Invalid size. Allowed sizes are {ALLOWED_SIZES}"}, status_code=400)

    workflow = load_workflow()

    original_img = Image.open(io.BytesIO(await original.read()))
    replacement_img = Image.open(io.BytesIO(await replacement.read()))
    
    original_name = send_image_to_comfyui(original_img, 140)
    replacement_name = send_image_to_comfyui(replacement_img, 218)

    run_id = run_workflow(workflow, [original_name, replacement_name])

    output_image = get_output_image(run_id)
    if output_image:
        # 결과 이미지 크기 조정
        resized_image = resize_image(output_image, size)
        encoded_image = base64.b64encode(resized_image).decode('utf-8')
        return JSONResponse(content={"image": encoded_image, "size": size})
    else:
        return JSONResponse(content={"error": "Failed to process images"}, status_code=500)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)