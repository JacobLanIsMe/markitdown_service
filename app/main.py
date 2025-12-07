from fastapi import FastAPI, UploadFile, File, HTTPException, Response
from markitdown import MarkItDown, FileConversionException, UnsupportedFormatException


app = FastAPI(title="markitdown-fastapi-demo")

@app.post("/convert_file_to_markdown")
async def convert_file_to_markdown(file: UploadFile = File(...)):
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
