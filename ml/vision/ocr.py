"""Provider-independent OCR interface, local Tesseract adapter, and offline mock engine.

Safety Directives:
1. OCR is strictly supporting evidence, NEVER the final authority on medicine equivalence.
2. Provider-independent architecture decouples local engines (Tesseract) from mock test runners.
3. Does not assume an engine is installed or download model checkpoints silently.
4. Preserves engine provenance, line-level coordinates, and confidence metadata.
"""

from abc import ABC, abstractmethod
from enum import Enum
import importlib.util
import shutil
import time
from typing import List, Optional
from PIL import Image
from io import BytesIO

from ml.schemas.ocr import OCRResult, OCRTextLine


class MockOCRPreset(str, Enum):
    """Synthetic OCR output presets aligned with vision extraction presets and safety edges."""
    AUGMENTIN_625_DUO = "AUGMENTIN_625_DUO"
    GLYCOMET_500_PR = "GLYCOMET_500_PR"
    GLYCOMET_1000_PR_CONFLICT = "GLYCOMET_1000_PR_CONFLICT"
    AMOXI_ALONE_CONFLICT = "AMOXI_ALONE_CONFLICT"
    CAPSULE_FORM_CONFLICT = "CAPSULE_FORM_CONFLICT"
    IR_RELEASE_CONFLICT = "IR_RELEASE_CONFLICT"
    BLURRY_UNREADABLE = "BLURRY_UNREADABLE"
    MALFORMED_OUTPUT = "MALFORMED_OUTPUT"
    NON_MEDICINE = "NON_MEDICINE"


class BaseOCREngine(ABC):
    """Abstract interface defining the contract for local Optical Character Recognition engines."""

    @abstractmethod
    def is_available(self) -> bool:
        """Returns True if the underlying OCR engine binary and dependencies are installed."""
        pass

    @abstractmethod
    def extract_text(self, image_bytes: bytes) -> OCRResult:
        """Extracts structured text lines and raw plaintext from a single image payload."""
        pass

    def extract_text_batch(self, images: List[bytes]) -> List[OCRResult]:
        """Extracts structured text across a batch of 1 to 3 images."""
        return [self.extract_text(img) for img in images]


class TesseractOCREngine(BaseOCREngine):
    """Local OCR engine leveraging Tesseract OCR via pytesseract or system CLI.
    
    Setup Requirements on Windows:
    1. Install Tesseract binary: `winget install UB-Mannheim.TesseractOCR` or `choco install tesseract`
    2. Install Python wrapper: `pip install pytesseract`
    3. Ensure `tesseract.exe` is added to system PATH or configure tesseract_cmd path.
    """

    def __init__(self, tesseract_cmd: Optional[str] = None):
        self.tesseract_cmd = tesseract_cmd
        self._is_installed = self._check_installation()

    def _check_installation(self) -> bool:
        """Verifies whether pytesseract and the tesseract executable are reachable."""
        pytesseract_spec = importlib.util.find_spec("pytesseract")
        if pytesseract_spec is None:
            return False

        if self.tesseract_cmd:
            return shutil.which(self.tesseract_cmd) is not None

        return shutil.which("tesseract") is not None

    def is_available(self) -> bool:
        return self._is_installed

    def extract_text(self, image_bytes: bytes) -> OCRResult:
        if not self._is_installed:
            return OCRResult(
                engine_name="tesseract",
                is_successful=False,
                raw_text="",
                lines=[],
                mean_confidence=0.0,
                error_message=(
                    "Tesseract OCR is not installed or not found on PATH. "
                    "Install via: 'winget install UB-Mannheim.TesseractOCR' and 'pip install pytesseract'."
                ),
            )

        start_time = time.time()
        try:
            import pytesseract
            if self.tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd

            with Image.open(BytesIO(image_bytes)) as pil_img:
                rgb_img = pil_img.convert("RGB")
                data = pytesseract.image_to_data(rgb_img, output_type=pytesseract.Output.DICT)

            lines: List[OCRTextLine] = []
            current_line_text: List[str] = []
            current_line_confs: List[float] = []
            current_line_num = -1
            line_box = None

            n_boxes = len(data.get("text", []))
            for i in range(n_boxes):
                text_word = data["text"][i].strip()
                conf = float(data["conf"][i])
                line_idx = data["line_num"][i]

                if not text_word or conf < 0:
                    continue

                if line_idx != current_line_num and current_line_text:
                    full_line = " ".join(current_line_text)
                    avg_c = float(sum(current_line_confs) / len(current_line_confs) / 100.0)
                    lines.append(OCRTextLine(
                        line_number=len(lines),
                        text=full_line,
                        confidence=round(max(0.0, min(1.0, avg_c)), 3),
                        bounding_box=line_box,
                    ))
                    current_line_text = []
                    current_line_confs = []

                current_line_num = line_idx
                current_line_text.append(text_word)
                current_line_confs.append(conf)
                if line_box is None:
                    line_box = [data["left"][i], data["top"][i], data["width"][i], data["height"][i]]
                else:
                    line_box[2] = (data["left"][i] + data["width"][i]) - line_box[0]
                    line_box[3] = max(line_box[3], data["height"][i])

            if current_line_text:
                full_line = " ".join(current_line_text)
                avg_c = float(sum(current_line_confs) / len(current_line_confs) / 100.0)
                lines.append(OCRTextLine(
                    line_number=len(lines),
                    text=full_line,
                    confidence=round(max(0.0, min(1.0, avg_c)), 3),
                    bounding_box=line_box,
                ))

            raw_text = "\n".join(l.text for l in lines)
            mean_conf = round(sum(l.confidence for l in lines) / len(lines), 3) if lines else 0.0
            latency = int((time.time() - start_time) * 1000)

            return OCRResult(
                engine_name="tesseract",
                is_successful=True,
                raw_text=raw_text,
                lines=lines,
                mean_confidence=mean_conf,
                latency_ms=latency,
            )

        except Exception as exc:
            return OCRResult(
                engine_name="tesseract",
                is_successful=False,
                raw_text="",
                lines=[],
                mean_confidence=0.0,
                error_message=f"Tesseract OCR processing failed: {str(exc)}",
            )


class MockOCREngine(BaseOCREngine):
    """Deterministic offline mock OCR engine for automated testing and CI pipelines."""

    def __init__(self, default_preset: MockOCRPreset = MockOCRPreset.AUGMENTIN_625_DUO):
        self.current_preset = default_preset
        self._queued_results: List[OCRResult] = []
        self._should_simulate_failure: bool = False
        self._simulated_error: Optional[str] = None
        self.call_count: int = 0

    def is_available(self) -> bool:
        return True

    def set_preset(self, preset: MockOCRPreset) -> None:
        """Sets the active preset OCR response."""
        self.current_preset = preset

    def queue_result(self, result: OCRResult) -> None:
        """Queues an explicit custom OCR result for the next extraction call."""
        self._queued_results.append(result)

    def set_failure_mode(self, error_message: str = "Simulated OCR timeout or process failure.") -> None:
        """Configures the mock to return an error result."""
        self._should_simulate_failure = True
        self._simulated_error = error_message

    def clear_failure_mode(self) -> None:
        """Clears failure mode."""
        self._should_simulate_failure = False
        self._simulated_error = None

    def _generate_preset_result(self, preset: MockOCRPreset) -> OCRResult:
        if preset == MockOCRPreset.AUGMENTIN_625_DUO:
            lines = [
                OCRTextLine(line_number=0, text="Augmentin 625 Duo", confidence=0.96, bounding_box=[20, 30, 200, 30]),
                OCRTextLine(line_number=1, text="Amoxycillin and Potassium Clavulanate Tablets IP", confidence=0.94, bounding_box=[20, 65, 300, 25]),
                OCRTextLine(line_number=2, text="Each film coated tablet contains:", confidence=0.90, bounding_box=[20, 95, 250, 20]),
                OCRTextLine(line_number=3, text="Amoxycillin Trihydrate IP equivalent to Amoxycillin 500 mg", confidence=0.95, bounding_box=[20, 120, 320, 20]),
                OCRTextLine(line_number=4, text="Potassium Clavulanate IP equivalent to Clavulanic Acid 125 mg", confidence=0.93, bounding_box=[20, 145, 330, 20]),
                OCRTextLine(line_number=5, text="Dosage: As directed by Physician", confidence=0.88, bounding_box=[20, 170, 220, 20]),
                OCRTextLine(line_number=6, text="GlaxoSmithKline Pharmaceuticals Ltd", confidence=0.92, bounding_box=[20, 200, 280, 20]),
            ]
            return OCRResult(
                engine_name="mock_ocr",
                is_successful=True,
                raw_text="\n".join(l.text for l in lines),
                lines=lines,
                mean_confidence=0.926,
                latency_ms=45,
            )

        elif preset == MockOCRPreset.GLYCOMET_500_PR:
            lines = [
                OCRTextLine(line_number=0, text="Glycomet 500 PR", confidence=0.98, bounding_box=[15, 25, 180, 30]),
                OCRTextLine(line_number=1, text="Metformin Hydrochloride Prolonged Release Tablets IP", confidence=0.95, bounding_box=[15, 60, 310, 25]),
                OCRTextLine(line_number=2, text="Each prolonged release tablet contains: Metformin Hydrochloride IP 500 mg", confidence=0.96, bounding_box=[15, 90, 340, 20]),
                OCRTextLine(line_number=3, text="USV Private Limited", confidence=0.94, bounding_box=[15, 120, 160, 20]),
            ]
            return OCRResult(
                engine_name="mock_ocr",
                is_successful=True,
                raw_text="\n".join(l.text for l in lines),
                lines=lines,
                mean_confidence=0.958,
                latency_ms=30,
            )

        elif preset == MockOCRPreset.GLYCOMET_1000_PR_CONFLICT:
            lines = [
                OCRTextLine(line_number=0, text="Glycomet 1000 PR", confidence=0.97, bounding_box=[15, 25, 180, 30]),
                OCRTextLine(line_number=1, text="Metformin Hydrochloride Prolonged Release Tablets IP", confidence=0.95, bounding_box=[15, 60, 310, 25]),
                OCRTextLine(line_number=2, text="Each prolonged release tablet contains: Metformin Hydrochloride IP 1000 mg", confidence=0.96, bounding_box=[15, 90, 340, 20]),
            ]
            return OCRResult(
                engine_name="mock_ocr",
                is_successful=True,
                raw_text="\n".join(l.text for l in lines),
                lines=lines,
                mean_confidence=0.96,
                latency_ms=32,
            )

        elif preset == MockOCRPreset.AMOXI_ALONE_CONFLICT:
            lines = [
                OCRTextLine(line_number=0, text="Amoxil 500", confidence=0.95, bounding_box=[20, 30, 150, 30]),
                OCRTextLine(line_number=1, text="Amoxycillin Capsules IP 500 mg", confidence=0.93, bounding_box=[20, 65, 260, 25]),
            ]
            return OCRResult(
                engine_name="mock_ocr",
                is_successful=True,
                raw_text="\n".join(l.text for l in lines),
                lines=lines,
                mean_confidence=0.94,
                latency_ms=25,
            )

        elif preset == MockOCRPreset.CAPSULE_FORM_CONFLICT:
            lines = [
                OCRTextLine(line_number=0, text="Amoxicillin 500mg Hard Gelatin Capsules", confidence=0.92, bounding_box=[20, 30, 300, 30]),
            ]
            return OCRResult(
                engine_name="mock_ocr",
                is_successful=True,
                raw_text="\n".join(l.text for l in lines),
                lines=lines,
                mean_confidence=0.92,
                latency_ms=22,
            )

        elif preset == MockOCRPreset.IR_RELEASE_CONFLICT:
            lines = [
                OCRTextLine(line_number=0, text="Metformin Immediate Release Tablets 500mg", confidence=0.94, bounding_box=[20, 30, 310, 30]),
            ]
            return OCRResult(
                engine_name="mock_ocr",
                is_successful=True,
                raw_text="\n".join(l.text for l in lines),
                lines=lines,
                mean_confidence=0.94,
                latency_ms=20,
            )

        elif preset == MockOCRPreset.BLURRY_UNREADABLE:
            lines = [
                OCRTextLine(line_number=0, text="... #%@?? ...", confidence=0.18, bounding_box=[20, 30, 100, 20]),
            ]
            return OCRResult(
                engine_name="mock_ocr",
                is_successful=True,
                raw_text="... #%@?? ...",
                lines=lines,
                mean_confidence=0.18,
                latency_ms=18,
            )

        elif preset == MockOCRPreset.MALFORMED_OUTPUT:
            return OCRResult(
                engine_name="mock_ocr",
                is_successful=False,
                raw_text="",
                lines=[],
                mean_confidence=0.0,
                error_message="OCR engine crashed: Segmentation fault or unhandled format exception.",
                latency_ms=5,
            )

        elif preset == MockOCRPreset.NON_MEDICINE:
            lines = [
                OCRTextLine(line_number=0, text="Sunlight Dishwashing Liquid 500ml", confidence=0.97, bounding_box=[10, 20, 250, 30]),
                OCRTextLine(line_number=1, text="Lemon Fresh Sparkle", confidence=0.91, bounding_box=[10, 60, 180, 20]),
            ]
            return OCRResult(
                engine_name="mock_ocr",
                is_successful=True,
                raw_text="\n".join(l.text for l in lines),
                lines=lines,
                mean_confidence=0.94,
                latency_ms=28,
            )

        raise ValueError(f"Unknown mock OCR preset: {preset}")

    def extract_text(self, image_bytes: bytes) -> OCRResult:
        self.call_count += 1
        if not image_bytes:
            raise ValueError("OCR engine requires at least 1 byte of image payload.")

        if self._should_simulate_failure:
            return OCRResult(
                engine_name="mock_ocr",
                is_successful=False,
                raw_text="",
                lines=[],
                mean_confidence=0.0,
                error_message=self._simulated_error or "Simulated OCR failure.",
            )

        if self._queued_results:
            return self._queued_results.pop(0)

        return self._generate_preset_result(self.current_preset)
