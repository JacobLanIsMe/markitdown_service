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
       
        pipeline_options = PdfPipelineOptions()
        pipeline_options.enable_remote_services = True
        pipeline_options.do_picture_description = True
        pipeline_options.picture_description_options = vllm_local_options(model="qwen3-vl:8b")
        
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
        prompt = (
            "請將此檔案中的『所有文字提取』與『視覺分析』整合成一個完整且連貫的專業描述段落。\n\n"
            "1. 必須精確識別並提取檔案中所有的文字內容，並將其自然嵌入在敘述中。文字必須**維持原始語言**，嚴禁翻譯。\n"
            "2. 描述需精確識別檔案中的所有物體、場景、圖示、色彩等視覺元素。\n"
        ),
        timeout=60000,
    )
    return options

