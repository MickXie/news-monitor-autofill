"""Apple Vision 文字辨識（macOS 內建，本機執行、免費）。

輸入 numpy RGB 影像，回傳 [(文字, 信心, (x0, y0, x1, y1))]，座標為像素、原點左上。
"""
from __future__ import annotations

import numpy as np
import Quartz
import Vision
from Foundation import NSData


def _to_cgimage(rgb: np.ndarray):
    h, w, _ = rgb.shape
    rgba = np.dstack([rgb, np.full((h, w), 255, np.uint8)]).astype(np.uint8)
    data = NSData.dataWithBytes_length_(rgba.tobytes(), rgba.nbytes)
    provider = Quartz.CGDataProviderCreateWithCFData(data)
    cs = Quartz.CGColorSpaceCreateDeviceRGB()
    return Quartz.CGImageCreate(
        w, h, 8, 32, w * 4, cs,
        Quartz.kCGImageAlphaNoneSkipLast, provider, None, False,
        Quartz.kCGRenderingIntentDefault,
    )


def ocr(rgb: np.ndarray, fast: bool = False, langs=("zh-Hant", "en-US")):
    h, w, _ = rgb.shape
    img = _to_cgimage(rgb)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(1 if fast else 0)  # 0 = accurate
    req.setRecognitionLanguages_(list(langs))
    req.setUsesLanguageCorrection_(False)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(img, None)
    ok, err = handler.performRequests_error_([req], None)
    out = []
    if not ok:
        return out
    for obs in req.results() or []:
        cand = obs.topCandidates_(1)
        if not cand:
            continue
        c = cand[0]
        bb = obs.boundingBox()  # 正規化座標，原點左下
        x0 = bb.origin.x * w
        x1 = (bb.origin.x + bb.size.width) * w
        y1 = (1 - bb.origin.y) * h
        y0 = (1 - bb.origin.y - bb.size.height) * h
        out.append((str(c.string()), float(c.confidence()), (x0, y0, x1, y1)))
    return out


def ocr_text(rgb: np.ndarray, **kw) -> str:
    """把辨識結果依由左到右串成一行。"""
    items = sorted(ocr(rgb, **kw), key=lambda t: t[2][0])
    return " ".join(t[0] for t in items).strip()
