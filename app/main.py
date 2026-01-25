from fastapi import FastAPI, UploadFile, File, HTTPException, Response
from markitdown import MarkItDown, FileConversionException, UnsupportedFormatException
import tempfile
import os
import asyncio
from pathlib import Path
from docling.datamodel.base_models import InputFormat

from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import PictureItem
from docling.datamodel.pipeline_options import (PdfPipelineOptions, PictureDescriptionApiOptions, VlmPipelineOptions, granite_picture_description)
from docling.datamodel.pipeline_options_vlm_model import ApiVlmOptions, ResponseFormat
from docling.pipeline.vlm_pipeline import VlmPipeline

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
       
        pipeline_options = VlmPipelineOptions(
            enable_remote_services=True  # required when calling remote VLM endpoints
        )
        pipeline_options.vlm_options = ollama_vlm_options(
            model="qwen3-vl:4b"
        )

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=pipeline_options,
                    pipeline_cls=VlmPipeline,
                )
            }
        )
        # Run the potentially blocking conversion in a thread
        result = await asyncio.to_thread(converter.convert, tmp_path)
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
        prompt = (
            "請將此檔案中的『所有文字提取』與『視覺分析』整合成一個完整且連貫的專業描述段落。\n\n"
            "1. 必須精確識別並提取檔案中所有的文字內容，並將其自然嵌入在敘述中。文字必須**維持原始語言**，嚴禁翻譯。\n"
            "2. 描述需包含出現的物體、場景、圖示、色彩等視覺元素。\n"
        ),
        timeout=6000,
    )
    return options

def ollama_vlm_options(model: str):
    options = ApiVlmOptions(
        url="http://localhost:11434/v1/chat/completions",  # the default Ollama endpoint
        params=dict(
            model=model,
        ),
        prompt=(
            "# 檔案轉換需求：整合式視覺與文字分析\n"
            "請讀取此檔案，並依照其**原始排版順序**，將視覺描述與文字內容整合為一份 **Markdown 文件**。請遵循以下原則：\n"
            "### 1. 整合式結構 (Integrated Structure)\n"
            "* **按序描述**：請由上而下、由左至右，依照檔案的視覺流向進行解析。\n"
            "* **圖文融合**：針對每一個視覺區塊（如標題區、側邊欄、圖表、產品圖等），先描述其**視覺特徵**（物體、顏色、風格），緊接著提取該區塊內的**文字內容**。\n"
            "* **排版還原**：使用 Markdown 標題 (H1-H3) 代表層級，使用區塊引用 (Blockquotes) 或列表來區分視覺描述與實際文字。\n"
            "### 2. 文字提取規範 (Text Extraction)\n"
            "* **精確提取**：完整保留所有文字，不得刪減。\n"
            "* **嚴禁翻譯**：文字必須**維持原始語言**（如英文維持英文、中文維持中文）。\n"
            "### 3. 視覺細節描述 (Visual Details)\n"
            "* **元素與風格**：描述該區塊的所有物體、色彩、光影氛圍、圖示樣式及物件位置。\n"
            "* **情境關聯**：解釋視覺元素是如何與文字內容產生關聯的（例如：文字位於紅色高亮區塊內）。\n"
        ),
        timeout=90,
        scale=1.0,
        response_format=ResponseFormat.MARKDOWN,
    )
    return options