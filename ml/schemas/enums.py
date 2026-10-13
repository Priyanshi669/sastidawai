"""Core enumerations representing workflow states, match tiers, and medicine dimensions."""

from enum import Enum


class ScanWorkflowState(str, Enum):
    """Workflow state of the perception and capture pipeline.
    
    CRITICAL: This represents image/extraction status, NOT medical equivalence.
    """
    REJECT_IMAGE = "REJECT_IMAGE"
    RETAKE_REQUIRED = "RETAKE_REQUIRED"
    EXTRACTION_INCOMPLETE = "EXTRACTION_INCOMPLETE"
    NEEDS_USER_CONFIRMATION = "NEEDS_USER_CONFIRMATION"
    READY_FOR_MATCHING = "READY_FOR_MATCHING"
    RECOVERABLE_ERROR = "RECOVERABLE_ERROR"


class MatchTier(str, Enum):
    """Deterministic medical equivalence classification tier.
    
    Assigned exclusively by the deterministic rule engine, never by LLM or heuristics.
    """
    EXACT = "exact"
    CLOSE = "close"
    NONE = "none"


class DosageForm(str, Enum):
    """Controlled dosage form vocabulary."""
    TABLET = "tablet"
    CAPSULE = "capsule"
    SYRUP = "syrup"
    SUSPENSION = "suspension"
    INJECTION = "injection"
    GEL = "gel"
    CREAM = "cream"
    DROPS = "drops"
    INHALER = "inhaler"
    OTHER = "other"
    UNKNOWN = "unknown"


class ReleaseType(str, Enum):
    """Controlled release mechanism vocabulary.
    
    IR and SR/ER/XR/MR are NEVER therapeutically interchangeable in EXACT tier.
    """
    IR = "IR"
    SR = "SR"
    ER = "ER"
    XR = "XR"
    DR_EC = "DR/EC"
    MR = "MR"
    ODT = "ODT"
    CHEWABLE = "chewable"
    DISPERSIBLE = "dispersible"
    UNKNOWN = "unknown"


class AdministrationRoute(str, Enum):
    """Controlled route of administration."""
    ORAL = "oral"
    TOPICAL = "topical"
    OPHTHALMIC = "ophthalmic"
    PARENTERAL = "parenteral"
    NASAL = "nasal"
    INHALATION = "inhalation"
    UNKNOWN = "unknown"


class LegibilityGrade(str, Enum):
    """Perception legibility classification."""
    GOOD = "good"
    PARTIAL = "partial"
    POOR = "poor"


class RxSchedule(str, Enum):
    """Indian regulatory prescription schedules (informational only; never authorizes dispensing)."""
    SCHEDULE_H = "H"
    SCHEDULE_H1 = "H1"
    SCHEDULE_X = "X"
    OTC = "OTC"
    UNKNOWN = "unknown"
