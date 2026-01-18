from fastapi import FastAPI, UploadFile, File, HTTPException, Response
from markitdown import MarkItDown, FileConversionException, UnsupportedFormatException
import tempfile
import os
import asyncio
from pathlib import Path
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions

from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import granite_picture_description
# from docling_core.types.doc import PictureItem


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
        pipeline_options.do_picture_description = True
        pipeline_options.picture_description_options = (
            granite_picture_description
        )
        pipeline_options.picture_description_options.prompt = (
            "Please act as a Retail Operations & Marketing Expert. Analyze the provided image and provide a concise yet professional summary based on its content:\n\n"
            "1. If the image is a PRODUCT or STORE DISPLAY:\n\n"
            "Product Details: Identify the product(s), branding, and key physical features (color, material, packaging).\n\n"
            "Consumer Perspective: Describe the 'vibe' (e.g., luxury, value-for-money, organic) and its potential target audience.\n\n"
            "Context & Promotion: Describe the setting (shelf, catalog, or lifestyle) and identify any visible pricing or promotional tags.\n\n"
            "2. If the image is a REPORT, CHART, or TABLE:\n\n"
            "Data Summary: What is the main metric being tracked? (e.g., Monthly Sales, Inventory Levels, Customer Traffic).\n\n"
            "Key Findings: Identify the most significant data points (e.g., peak performance, lowest dips, or sudden changes).\n\n"
            "Business Insight: What is the 'takeaway' or trend that a manager should notice immediately?\n\n"
            "3. Summary Conclusion:\n\n"
            "Provide a 3 to 5 sentence summary of the image's key information.\n\n"
            "Focus on describing the current state, facts, and essential details.\n\n"
            "Keep the tone objective and professional."
        )
        pipeline_options.images_scale = 2.0
        pipeline_options.generate_page_images = True
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
