"""
ocr_runner.py — Windows 內建 OCR 呼叫包裝

職責：
  1. 將 Base64 圖片資料寫入暫存檔
  2. 呼叫 ocr.ps1（透過 PowerShell）
  3. 讀取結果，清理後回傳文字
  4. 清除暫存檔

安全注意事項：
  - 暫存檔使用 tempfile.mkstemp，避免路徑注入
  - PowerShell 指令使用參數陣列而非字串拼接
  - timeout 預設 30 秒，避免 OCR 卡住整個請求
"""

from __future__ import annotations

import base64
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ocr.ps1 路徑（相對於本檔案的上層目錄，即專案根目錄）
_OCR_SCRIPT = Path(__file__).parent.parent / "ocr.ps1"

# OCR 逾時秒數
OCR_TIMEOUT = 30

# 全形→半形對照，與 analyzer.py 的 tidyCJK 一致
_HALF_FULL_TABLE = str.maketrans(
    "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ",
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
)
_CJK_RE = re.compile(
    r'([\u3000-\u303f\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]) '
    r'(?=[\u3000-\u303f\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef0-9A-Za-z])'
) if False else None  # 延遲 import re


def _tidy_ocr_text(raw: str) -> str:
    """清理 OCR 輸出：全形轉半形、移除中文字間多餘空格、合併多餘換行。"""
    import re
    text = raw.translate(_HALF_FULL_TABLE)
    # 中文字之間的空白去掉
    cjk = r'[\u3000-\u303f\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]'
    text = re.sub(rf'({cjk}) (?=[{cjk[1:-1]}0-9A-Za-z])', r'\1', text)
    text = re.sub(rf'([0-9A-Za-z]) (?=[{cjk[1:-1]}])', r'\1', text)
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


class OcrError(Exception):
    """OCR 執行失敗時拋出"""


def run_ocr(image_base64: str, media_type: str = "image/png") -> str:
    """
    對圖片執行 Windows 內建 OCR，回傳識別文字。

    Parameters
    ----------
    image_base64 : str
        圖片 Base64 編碼（不含 data: 前綴）
    media_type : str
        圖片 MIME type（決定暫存檔副檔名）

    Returns
    -------
    str
        清理過的 OCR 識別文字，無文字時回傳空字串

    Raises
    ------
    OcrError
        OCR 腳本不存在、執行失敗、或逾時
    """
    if not _OCR_SCRIPT.exists():
        raise OcrError(f"找不到 OCR 腳本：{_OCR_SCRIPT}")

    # 決定副檔名
    ext_map = {
        "image/jpeg": ".jpg",
        "image/png":  ".png",
        "image/webp": ".webp",
        "image/gif":  ".gif",
    }
    ext = ext_map.get(media_type.lower(), ".png")

    # 寫入暫存檔
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=ext)
    try:
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(base64.b64decode(image_base64))

        # 呼叫 PowerShell（參數陣列，避免注入）
        cmd = [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy", "Bypass",
            "-File", str(_OCR_SCRIPT),
            tmp_path,
        ]
        logger.debug("執行 OCR：%s", tmp_path)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=OCR_TIMEOUT,
        )

        if result.returncode == 2:
            # ocr.ps1 的 exit 2 代表沒有可用的 OCR 語言套件
            raise OcrError("Windows OCR 語言套件不可用（NO_OCR_LANGUAGE）")

        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise OcrError(f"OCR 腳本執行失敗（exit {result.returncode}）：{stderr[:200]}")

        raw = result.stdout
        return _tidy_ocr_text(raw)

    except subprocess.TimeoutExpired:
        raise OcrError(f"OCR 辨識逾時（>{OCR_TIMEOUT}s），請確認圖片大小或系統資源。")
    except OcrError:
        raise
    except Exception as e:
        raise OcrError(f"OCR 執行時發生未預期錯誤：{e}") from e
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def is_ocr_available() -> bool:
    """
    快速檢查 OCR 功能是否可用（腳本存在且 PowerShell 可執行）。
    用於 /api/status。
    """
    if not _OCR_SCRIPT.exists():
        return False
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", "exit 0"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False
