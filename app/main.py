from fastapi import FastAPI, UploadFile, File, HTTPException, Response
from markitdown import MarkItDown, FileConversionException, UnsupportedFormatException
import tempfile
import os
import asyncio
from pathlib import Path
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    PictureDescriptionApiOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import PictureItem


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
        picture_description_options = PictureDescriptionApiOptions(
            url="http://localhost:5037/Chat/PictureDescription",
            params=dict(
                model="model",
                seed=42,
                max_completion_tokens=200,
            ),
            prompt="Describe the image in three sentences. Be consise and accurate.",
            timeout=72000
        )
        pipeline_options = PdfPipelineOptions(
            enable_remote_services=True  # <-- this is required!
        )
        pipeline_options.do_picture_description = True
        pipeline_options.picture_description_options = picture_description_options
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=pipeline_options,
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
