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
       
        pipeline_options = PdfPipelineOptions(
            enable_remote_services=True  # <-- this is required!
        )
        pipeline_options.do_picture_description = True
        pipeline_options.picture_description_options = vllm_local_options("qwen3-vl:8b")

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=pipeline_options
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
        timeout=900000,
        scale=2.0,
        response_format=ResponseFormat.MARKDOWN,
    )
    return options

def google_local_options():
    options = PictureDescriptionApiOptions(
        url="http://localhost:5037/Chat/PictureDescription",
        params=dict(
            model="gemini",
            seed=42,
            max_completion_tokens=200,
        ),
        prompt="Describe the image in three sentences. Be consise and accurate.",
        timeout=900000,
    )
    return options