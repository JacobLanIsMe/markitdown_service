from fastapi import FastAPI, UploadFile, File, HTTPException, Response
from markitdown import MarkItDown, FileConversionException, UnsupportedFormatException
import tempfile
import os
import asyncio
from pathlib import Path
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions

from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import PictureItem, TableItem, ImageRefMode
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
       
        output_dir = Path("scratch")

        pipeline_options = PdfPipelineOptions()
        pipeline_options.images_scale = 2.0
        pipeline_options.generate_page_images = True
        pipeline_options.generate_picture_images = True
        
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=pipeline_options,
                )
            }
        )
        # Run the potentially blocking conversion in a thread
        result = await asyncio.to_thread(converter.convert, tmp_path)
        output_dir.mkdir(parents=True, exist_ok=True)
        doc_filename = result.input.file.stem
        
        # Save page images
        for page_no, page in result.document.pages.items():
            page_no = page.page_no
            page_image_filename = output_dir / f"{doc_filename}-{page_no}.png"
            with page_image_filename.open("wb") as fp:
                page.image.pil_image.save(fp, format="PNG")

        # Save images of figures and tables
        table_counter = 0
        picture_counter = 0
        for element, _level in result.document.iterate_items():
            if isinstance(element, TableItem):
                table_counter += 1
                element_image_filename = (
                    output_dir / f"{doc_filename}-table-{table_counter}.png"
                )
                with element_image_filename.open("wb") as fp:
                    element.get_image(result.document).save(fp, "PNG")

            if isinstance(element, PictureItem):
                picture_counter += 1
                element_image_filename = (
                    output_dir / f"{doc_filename}-picture-{picture_counter}.png"
                )
                with element_image_filename.open("wb") as fp:
                    element.get_image(result.document).save(fp, "PNG")
        # Save markdown with embedded pictures
        md_filename = output_dir / f"{doc_filename}-with-images.md"
        result.document.save_as_markdown(md_filename, image_mode=ImageRefMode.EMBEDDED)

        # Save markdown with externally referenced pictures
        md_filename = output_dir / f"{doc_filename}-with-image-refs.md"
        result.document.save_as_markdown(md_filename, image_mode=ImageRefMode.REFERENCED)

        # Save HTML with externally referenced pictures
        html_filename = output_dir / f"{doc_filename}-with-image-refs.html"
        result.document.save_as_html(html_filename, image_mode=ImageRefMode.REFERENCED)
        
        
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
            "請將此檔案中的『所有文字』與『所有物體』整合成一個完整且連貫的專業描述段落。\n\n"
            "1. 必須完整且精確識別並提取檔案中所有的文字內容，並將其自然嵌入在敘述中。文字必須**維持原始語言**，嚴禁翻譯。\n"
            "2. 描述需精確識別檔案中的所有物體、場景、圖示、色彩等視覺元素。\n"
        ),
        timeout=60000,
    )
    return options

