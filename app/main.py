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
import re
import json
import requests


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
        
        # # Save page images
        # for page_no, page in result.document.pages.items():
        #     page_no = page.page_no
        #     page_image_filename = output_dir / f"{doc_filename}-{page_no}.png"
        #     with page_image_filename.open("wb") as fp:
        #         page.image.pil_image.save(fp, format="PNG")

        # # Save images of figures and tables
        # table_counter = 0
        # picture_counter = 0
        # for element, _level in result.document.iterate_items():
        #     if isinstance(element, TableItem):
        #         table_counter += 1
        #         element_image_filename = (
        #             output_dir / f"{doc_filename}-table-{table_counter}.png"
        #         )
        #         with element_image_filename.open("wb") as fp:
        #             element.get_image(result.document).save(fp, "PNG")

        #     if isinstance(element, PictureItem):
        #         picture_counter += 1
        #         element_image_filename = (
        #             output_dir / f"{doc_filename}-picture-{picture_counter}.png"
        #         )
        #         with element_image_filename.open("wb") as fp:
        #             element.get_image(result.document).save(fp, "PNG")
                
        # Save markdown with embedded pictures
        md_filename = output_dir / f"{doc_filename}-with-images.md"
        result.document.save_as_markdown(md_filename, image_mode=ImageRefMode.EMBEDDED)

        # # Save markdown with externally referenced pictures
        # md_filename = output_dir / f"{doc_filename}-with-image-refs.md"
        # result.document.save_as_markdown(md_filename, image_mode=ImageRefMode.REFERENCED)

        # # Save HTML with externally referenced pictures
        # html_filename = output_dir / f"{doc_filename}-with-image-refs.html"
        # result.document.save_as_html(html_filename, image_mode=ImageRefMode.REFERENCED)
        
        
        # Prefer the saved markdown file and run PictureIntegration on it so
        # embedded base64 images are replaced by descriptions. If that fails,
        # fall back to the document's export_to_markdown().
        markdown = ""
        try:
            integrated = PictureIntegration(str(md_filename))
            markdown = integrated
        except Exception:
            # fallback to doc export
            markdown = result.document.export_to_markdown()

        return Response(content=markdown or "", media_type="text/markdown")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Docling conversion failed: {str(e)}")
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

def vllm_local_options(model: str):
    # 使用三引號來處理多行字串，這樣可以保持 Markdown 的格式
    prompt_content = """# 檔案轉換需求：極致精確文字擷取與視覺分析

請嚴格依序執行以下步驟，確保 **100% 擷取影像中所有文字**，並以繁體中文進行整合描述：

## 執行步驟

1. **極致文字掃描 (Strict Data Extraction)**：
   全面掃描影像。擷取所有可見文字（包含標題、段落、註腳、標籤、按鈕、日期、標誌旁的微縮文字、甚至背景中的模糊文字）。**必須保留文字原始語言與書寫方式，禁止任何翻譯、改寫、拼字修正或刪減。**

2. **全方位視覺建模 (Visual Detailing)**：
   詳盡描述影像的視覺屬性，包括版面佈局（如欄位、框線、表格結構）、配色方案（色彩、光影、反差）、物體、材質紋理、圖示/標誌類型、以及前景與背景的空間關係。

3. **強制作業：全文字核對與整合輸出**：
   將步驟 1 擷取的「每一個」文字片段與步驟 2 的描述融合成一個專業的繁體中文段落。
   * **核心要求**：此段落必須包含影像中出現的所有文字內容。文字必須以原始形式嵌入描述中，不得遺漏。
   * **連結邏輯**：在描述視覺元素時，必須同時說明該處所呈現的文字內容（例如：在深藍色橫幅中印有白色加粗的「[原始文字]」字樣）。

## 輸出要求（嚴格執行）

* **單一整合段落**：僅輸出一個專業且連貫的**繁體中文**段落。該段落必須包含影像中所有擷取到的原始文字，且邏輯通順。
* **Markdown 表格**：若影像包含表格，請在上述段落後立即輸出完整的 Markdown 表格。表格須完整呈現所有欄位與列，並保留表內文字的原始語言與書寫。
* **禁令**：禁止輸出步驟標籤（如：步驟 1...）、禁止自我評論（如：這是一張...）、禁止標題、禁止額外說明或總結。"""

    options = PictureDescriptionApiOptions(
        url="http://localhost:11434/v1/chat/completions",
        params=dict(
            model=model,
            seed=42,
            temperature=0.0,  # 降低隨機性，讓描述更精確
            max_completion_tokens=2048,
        ),
        prompt=prompt_content,
        timeout=6000000,
    )
    return options
 

def PictureDescription(base64_image_str: str) -> str:
    """Call local Ollama API to get a description for a base64 image string.

    Uses the same prompt content as `vllm_local_options()` to ensure identical
    prompt text. Returns the description text extracted from the Ollama response
    or an error placeholder on failure.
    """
    
    prompt_content = """
    # 檔案轉換需求：極致精確文字擷取與視覺分析

    請嚴格依序執行以下步驟，確保 **100% 擷取影像中所有文字**，並以繁體中文進行整合描述：

    ## 執行步驟

    1. **極致文字掃描 (Strict Data Extraction)**：
    全面掃描影像。擷取所有可見文字（包含標題、段落、註腳、標籤、按鈕、日期、標誌旁的微縮文字、甚至背景中的模糊文字）。**必須保留文字原始語言與書寫方式，禁止任何翻譯、改寫、拼字修正或刪減。**

    2. **全方位視覺建模 (Visual Detailing)**：
    詳盡描述影像的視覺屬性，包括版面佈局（如欄位、框線、表格結構）、配色方案（色彩、光影、反差）、物體、材質紋理、圖示/標誌類型、以及前景與背景的空間關係。

    3. **強制作業：全文字核對與整合輸出**：
    將步驟 1 擷取的「每一個」文字片段與步驟 2 的描述融合成一個專業的繁體中文段落。
    * **核心要求**：此段落必須包含影像中出現的所有文字內容。文字必須以原始形式嵌入描述中，不得遺漏。
    * **連結邏輯**：在描述視覺元素時，必須同時說明該處所呈現的文字內容（例如：在深藍色橫幅中印有白色加粗的「[原始文字]」字樣）。

    ## 輸出要求（嚴格執行）

    * **單一整合段落**：僅輸出一個專業且連貫的**繁體中文**段落。該段落必須包含影像中所有擷取到的原始文字，且邏輯通順。
    * **Markdown 表格**：若影像包含表格，請在上述段落後立即輸出完整的 Markdown 表格。表格須完整呈現所有欄位與列，並保留表內文字的原始語言與書寫。
    * **禁令**：禁止輸出步驟標籤（如：步驟 1...）、禁止自我評論（如：這是一張...）、禁止標題、禁止額外說明或總結。
    """

    url = "http://localhost:11434/v1/chat/completions"
    payload = {
        "model": "qwen3-vl:8b",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_content},
                    {"type": "image_url", "image_url": {"url": base64_image_str}},
                ],
            }
        ],
        "max_tokens": 2000,
    }

    try:
        # No timeout (None) — allow the Ollama service as long as needed.
        resp = requests.post(url, json=payload, timeout=None)
        resp.raise_for_status()
    except Exception as e:
        return f"[PictureDescription failed: {str(e)}]"

    try:
        j = resp.json()
    except Exception:
        return resp.text

    # Extract text from common response shapes
    choices = j.get("choices") if isinstance(j, dict) else None
    if choices and isinstance(choices, list) and len(choices) > 0:
        first = choices[0]
        # message.content may be string or list
        msg = first.get("message") if isinstance(first, dict) else None
        if isinstance(msg, dict):
            content = msg.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text = item.get("text")
                        if text:
                            return text
        text = first.get("text") if isinstance(first, dict) else None
        if isinstance(text, str) and text.strip():
            return text

    if isinstance(j, dict):
        for key in ("text", "output", "message", "description"):
            val = j.get(key)
            if isinstance(val, str) and val.strip():
                return val

    try:
        return json.dumps(j)
    except Exception:
        return str(j)


def PictureIntegration(md_filepath: str) -> str:
    """Read a markdown file, replace embedded base64 images with descriptions.

    Finds data URI base64 images (data:image/...;base64,...) and for each
    unique occurrence calls `PictureDescription()` then replaces the base64
    string with the returned description text. Returns the resulting content.
    """
    if not os.path.exists(md_filepath):
        raise FileNotFoundError(md_filepath)

    with open(md_filepath, "r", encoding="utf-8") as f:
        content = f.read()


    # Find markdown image tags and extract the URL part robustly (supports
    # multi-line base64 data URIs). Pattern captures the whole parentheses
    # content lazily to the next ')' allowing newlines.
    md_image_re = re.compile(r'!\[[^\]]*\]\((.*?)\)', re.DOTALL)

    seen = []
    for m in md_image_re.finditer(content):
        inner = m.group(1)  # content inside parentheses

        # Remove a trailing title like:  space "title"  or  space 'title'
        title_match = re.search(r"\s+(?:\".*\"|'.*')\s*$", inner, flags=re.DOTALL)
        url_part = inner[: title_match.start()].strip() if title_match else inner.strip()

        # If the url_part looks like a data URI image, normalize and process
        if url_part.startswith("data:image"):
            # If base64 has been wrapped with whitespace/newlines, remove them
            if "base64," in url_part:
                prefix, b64 = url_part.split("base64,", 1)
                b64_clean = re.sub(r"\s+", "", b64)
                data_uri_clean = prefix + "base64," + b64_clean
            else:
                data_uri_clean = url_part

            # Avoid duplicate processing
            if data_uri_clean in seen:
                continue
            seen.append(data_uri_clean)

            # Call PictureDescription and replace the original url_part
            desc = PictureDescription(data_uri_clean)

            # Replace only the url_part inside the parentheses, preserving
            # alt text and any title present.
            start, end = m.span(1)
            # reconstruct new parentheses content: replace url_part with desc
            new_inner = inner.replace(url_part, desc, 1)
            content = content[:start] + new_inner + content[end:]

    return content

