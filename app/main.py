from fastapi import FastAPI, UploadFile, File, HTTPException, Response
from markitdown import MarkItDown, FileConversionException, UnsupportedFormatException
import tempfile
import os
import asyncio
from pathlib import Path
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions

from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import PictureItem
from docling.datamodel.pipeline_options import (PdfPipelineOptions, PictureDescriptionApiOptions, granite_picture_description)


app = FastAPI(title="markitdown-fastapi-demo")

@app.post("/convert_file_to_markdown_by_markitdown")
async def convert_file_to_markdown_by_markitdown(file: UploadFile = File(...)):
    """Accept a single uploaded file and convert it to Markdown using markitdown.

    Returns a `text/markdown` response with the converted content.
    """
    # Basic validation
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    try:
        converter = MarkItDown()
        # Use convert_stream which accepts a file-like object with .read()
        result = converter.convert_stream(file.file)
        markdown = result.text_content if result is not None else ""
        return Response(content=markdown, media_type="text/markdown")
    except UnsupportedFormatException as e:
        raise HTTPException(status_code=415, detail=str(e))
    except FileConversionException as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        # Unexpected error
        raise HTTPException(status_code=500, detail=f"Conversion failed: {str(e)}")


@app.post("/convert_file_to_markdown_by_docling")
async def convert_file_to_markdown_by_docling(file: UploadFile = File(...)):
    """Accept an uploaded file and convert it to Markdown using Docling.

    This endpoint writes the upload to a temporary file and calls Docling's
    DocumentConverter.convert() in a thread so it doesn't block the event loop.
    If `docling` isn't installed, returns 500 with an explanatory message.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    if DocumentConverter is None:
        raise HTTPException(status_code=500, detail="docling is not installed in the virtual environment")

    # Read upload into memory and write to a temp file
    try:
        contents = await file.read()
        suffix = Path(file.filename).suffix or ""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            tmp.write(contents)
            tmp.flush()
            tmp_path = tmp.name
        finally:
            tmp.close()
        # picture_description_options 裡面設定的參數都是假的，真的設定在後端服務。
        # picture_description_options = PictureDescriptionApiOptions(
        #     url="http://localhost:5037/Chat/PictureDescription",
        #     params=dict(
        #         model="model",
        #         seed=42,
        #         max_completion_tokens=200,
        #     ),
        #     prompt="Describe the image in three sentences. Be consise and accurate.",
        #     timeout=72000
        # )
        pipeline_options = PdfPipelineOptions()
        pipeline_options.enable_remote_services = True
        pipeline_options.do_picture_description = True
        pipeline_options.picture_description_options = vllm_local_options(model="qwen3-vl:8b")
        # pipeline_options.picture_description_options.prompt = (
        #     "Please act as a Retail Operations & Marketing Expert. Analyze the provided image and provide a concise yet professional summary based on its content:\n\n"
        #     "1. If the image is a PRODUCT or STORE DISPLAY:\n\n"
        #     "Product Details: Identify the product(s), branding, and key physical features (color, material, packaging).\n\n"
        #     "Consumer Perspective: Describe the 'vibe' (e.g., luxury, value-for-money, organic) and its potential target audience.\n\n"
        #     "Context & Promotion: Describe the setting (shelf, catalog, or lifestyle) and identify any visible pricing or promotional tags.\n\n"
        #     "2. If the image is a REPORT, CHART, or TABLE:\n\n"
        #     "Data Summary: What is the main metric being tracked? (e.g., Monthly Sales, Inventory Levels, Customer Traffic).\n\n"
        #     "Key Findings: Identify the most significant data points (e.g., peak performance, lowest dips, or sudden changes).\n\n"
        #     "Business Insight: What is the 'takeaway' or trend that a manager should notice immediately?\n\n"
        #     "3. Deep Visual Scan & Granular Description:\n\n"
        #     "Provide an exhaustive description of all visual elements present in the image.\n\n"
        #     "Focus on micro-details such as textures, lighting directions (e.g., soft key light, harsh shadows), "
        #     "background elements, color gradients, and the placement/spatial relationship of objects.\n\n"
        #     "Describe the presence of any text (logos, fine print, labels) or human presence (postures, expressions, hand-models).\n\n"
        #     "Aim for high technical density to ensure a person who hasn't seen the image can visualize it with 95% accuracy.\n\n"

        #     "Focus on describing the current state, facts, and essential details.\n\n"
        #     "Keep the tone objective and professional." \
        #     "Respond in Traditional Chinese."
        # )
        # pipeline_options.images_scale = 2.0
        # pipeline_options.generate_page_images = True
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=pipeline_options,
                )
            }
        )
        # Run the potentially blocking conversion in a thread
        result = await asyncio.to_thread(converter.convert, tmp_path)
        for element, _level in result.document.iterate_items():
            if isinstance(element, PictureItem):
                print(
                    f"Picture {element.self_ref}\n"
                    f"Caption: {element.caption_text(doc=result.document)}\n"
                    f"Meta: {element.meta}"
                )
        markdown = ""
        if result is not None and getattr(result, "document", None) is not None:
            try:
                markdown = result.document.export_to_markdown()
            except Exception:
                # Fallback if export method differs
                markdown = str(result)

        return Response(content=markdown or "", media_type="text/markdown")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Docling conversion failed: {str(e)}")
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

def vllm_local_options(model: str):
    options = PictureDescriptionApiOptions(
        url="http://localhost:11434/v1/chat/completions",
        params=dict(
            model=model, 
            seed=42,
            temperature=0.1, # 降低隨機性，讓描述更精確
            max_completion_tokens=1024, # 描述圖片通常 1k 內就綽綽有餘
        ),
        prompt="請仔細讀取此檔案並依照以下要求取得內容：\n\n"
                "### 1. 文字提取 (Text Extraction)\n\n"
                "* 請精確識別並提取檔案中所有的文字內容。\n\n"
                "* **重要條件：** 提取出的文字必須**維持其原始語言**（例如：英文維持英文、中文維持中文），**嚴禁進行翻譯**。\n\n"
                "### 2. 視覺分析 (Visual Analysis)\n\n"
                "* **物體與場景**：詳細描述檔案中的視覺元素，包含出現的物體、場景位置、背景環境、人物動作或圖示。\n\n"
                "* **顏色與風格**：詳細描述主要的色彩配置 (Color Palette)、光學氛圍以及整體的設計風格（如：極簡風、工業風等）。\n\n",
        timeout=600,
    )
    return options