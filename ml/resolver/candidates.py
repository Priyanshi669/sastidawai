"""Candidate resolver implementing deterministic normalized lookup and RapidFuzz lexical retrieval.

Safety Directives:
1. Deterministic normalized lookup against SQLite is executed first.
2. RapidFuzz is used ONLY to retrieve and rank candidates, NEVER to decide equivalence.
3. Every candidate is evaluated through the Phase 1C deterministic matcher.
4. Quarantined, discontinued, or insufficiently evidenced records cannot produce EXACT.
5. Unknown attributes are never assumed to match.
"""

from enum import Enum
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field
from rapidfuzz import fuzz, process
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ml.data.database import DEFAULT_DB_URL, get_db_session
from ml.data.models import ProductRecord, ProductSaltRecord
from ml.resolver.normalize import are_strengths_equivalent, normalize_salt_name, normalize_strength
from ml.safety.matcher import DeterministicMatcher, evaluate_single_pair
from ml.schemas.canonical import (
    ActiveSaltMoiety,
    CanonicalMedicine,
    PriceRecord,
    ProvenanceRecord,
)
from ml.schemas.enums import (
    AdministrationRoute,
    DosageForm,
    MatchTier,
    ReleaseType,
    ScanWorkflowState,
)
from ml.schemas.extraction import RawMedicineExtraction
from ml.schemas.matcher import MANDATORY_DISCLAIMER, MatchResult


class ResolverStatus(str, Enum):
    """Categorical status of candidate resolution."""
    CANDIDATES_FOUND = "CANDIDATES_FOUND"
    NO_CANDIDATE = "NO_CANDIDATE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


# Controlled chemical synonym map for retrieval expansion
MOIETY_SYNONYMS: Dict[str, Set[str]] = {
    "clavulanic acid": {"clavulanic acid", "clavulanate"},
    "clavulanate": {"clavulanic acid", "clavulanate"},
    "amoxicillin": {"amoxicillin", "amoxycillin", "amoxycillin trihydrate"},
    "amoxycillin": {"amoxicillin", "amoxycillin", "amoxycillin trihydrate"},
    "amoxycillin trihydrate": {"amoxicillin", "amoxycillin", "amoxycillin trihydrate"},
    "paracetamol": {"paracetamol", "acetaminophen"},
    "acetaminophen": {"paracetamol", "acetaminophen"},
    "albuterol": {"albuterol", "salbutamol"},
    "salbutamol": {"albuterol", "salbutamol"},
}


def are_moieties_equivalent(m1: str, m2: str) -> bool:
    """Checks whether two moiety strings are identical or documented chemical synonyms."""
    if m1 == m2:
        return True
    return m2 in MOIETY_SYNONYMS.get(m1, set())


def moiety_sets_match(set_a: Set[str], set_b: Set[str]) -> bool:
    """Order-independent equivalence check across two sets of active chemical moieties."""
    if len(set_a) != len(set_b):
        return False
    for a in set_a:
        if not any(are_moieties_equivalent(a, b) for b in set_b):
            return False
    return True


class CandidateRecord(BaseModel):
    """A candidate generic record retrieved from the catalogue with provenance and evidence."""
    product_id: str
    canonical_name: str
    retrieval_method: str  # 'deterministic_salt_match', 'deterministic_brand_lookup', 'fuzzy_lexical'
    lexical_score: float = Field(ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list)
    critical_conflicts: List[str] = Field(default_factory=list)
    requires_confirmation: bool = False
    canonical_medicine: CanonicalMedicine


class ResolverResult(BaseModel):
    """Complete output of candidate resolution."""
    status: ResolverStatus
    query_text: Optional[str] = None
    candidates: List[CandidateRecord] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


def product_record_to_canonical(rec: ProductRecord) -> CanonicalMedicine:
    """Pure conversion from SQLAlchemy ProductRecord to domain CanonicalMedicine schema."""
    dosage_form = DosageForm.UNKNOWN
    if rec.dosage_form in DosageForm._value2member_map_:
        dosage_form = DosageForm(rec.dosage_form)

    release_type = ReleaseType.UNKNOWN
    if rec.release_type in ReleaseType._value2member_map_:
        release_type = ReleaseType(rec.release_type)

    route = AdministrationRoute.UNKNOWN
    if rec.route in AdministrationRoute._value2member_map_:
        route = AdministrationRoute(rec.route)

    provenance = ProvenanceRecord(
        source_name=rec.source_name,
        source_row_id=rec.source_row_id,
        raw_text=rec.raw_name,
        retrieval_date="2026-10-13",
        price_date=rec.price_date if rec.price_date and rec.price_date != "unverified" else None,
        checksum_sha256=rec.source_file_sha256,
    )

    price_rec = PriceRecord(
        pack_mrp_inr=rec.mrp_inr,
        pack_count=rec.pack_count,
        unit_price_inr=rec.unit_price_inr,
        price_date=rec.price_date if rec.price_date != "unverified" else "2026-10-13",
        is_verified_current=rec.is_verified_price,
        provenance=provenance,
    )

    salts: List[ActiveSaltMoiety] = []
    for s in rec.salts:
        salts.append(
            ActiveSaltMoiety(
                salt_name=s.salt_name,
                salt_modifier=s.salt_modifier,
                strength_value=s.strength_value,
                strength_unit=s.strength_unit,
                per_unit=s.per_unit,
            )
        )

    return CanonicalMedicine(
        product_id=rec.id,
        name=rec.name,
        brand_name=rec.name if rec.kind == "brand" else None,
        generic_name=rec.name if rec.kind == "generic" else None,
        manufacturer=rec.manufacturer,
        dosage_form=dosage_form,
        release_type=release_type,
        route=route,
        price=price_rec,
        salts=salts,
        is_quarantined=rec.is_quarantined,
        quarantine_reason=rec.quarantine_reason,
        is_nti=False,
        is_discontinued=rec.is_discontinued,
        is_eligible_for_matching=rec.is_eligible_for_matching,
        provenance=provenance,
    )


class CandidateResolver:
    """Production candidate resolver combining deterministic lookup and RapidFuzz."""

    def __init__(self, db_url: str = DEFAULT_DB_URL, min_fuzzy_score: float = 55.0):
        self.db_url = db_url
        self.min_fuzzy_score = min_fuzzy_score

    def _get_generic_pool(self, session: Session) -> List[Tuple[str, str, ProductRecord]]:
        """Pre-loads active, unquarantined generic products for rapid fuzzy matching."""
        records = (
            session.query(ProductRecord)
            .filter_by(kind="generic", is_quarantined=False)
            .all()
        )
        return [(r.id, r.name, r) for r in records]

    def resolve_from_canonical(
        self,
        scanned: CanonicalMedicine,
        session: Optional[Session] = None,
        limit: int = 5,
    ) -> ResolverResult:
        """Resolves candidates for a structured scanned medicine record."""
        # 1. Check for Insufficient Evidence
        has_brand = bool(scanned.brand_name and scanned.brand_name.strip())
        has_salts = bool(scanned.salts and any(s.salt_name.strip() for s in scanned.salts))

        if not has_brand and not has_salts:
            return ResolverResult(
                status=ResolverStatus.INSUFFICIENT_EVIDENCE,
                warnings=["Neither brand name nor chemical composition provided; cannot retrieve candidates."],
            )

        close_session = False
        if session is None:
            session = get_db_session(self.db_url)
            close_session = True

        candidates: List[CandidateRecord] = []
        seen_ids: Set[str] = set()

        try:
            # 2. Deterministic Active Salt Lookup (Primary Path)
            scanned_moieties = {s.salt_name.strip().lower() for s in scanned.salts if s.salt_name}
            if scanned_moieties:
                expanded_query_moieties = set()
                for m in scanned_moieties:
                    expanded_query_moieties.update(MOIETY_SYNONYMS.get(m, {m}))

                # Find generic products matching any of the active salts
                salt_records = (
                    session.query(ProductSaltRecord)
                    .join(ProductRecord)
                    .filter(
                        ProductRecord.kind == "generic",
                        ProductRecord.is_quarantined == False,
                        ProductSaltRecord.salt_name.in_(list(expanded_query_moieties)),
                    )
                    .all()
                )

                # Group by product
                matched_product_ids = {s.product_id for s in salt_records}
                for pid in matched_product_ids:
                    prod = session.query(ProductRecord).filter_by(id=pid).first()
                    if prod and prod.id not in seen_ids:
                        canonical_prod = product_record_to_canonical(prod)
                        candidate_moieties = {s.salt_name for s in canonical_prod.salts}

                        evidence: List[str] = []
                        conflicts: List[str] = []

                        # Compute Evidence Flags
                        if moiety_sets_match(scanned_moieties, candidate_moieties):
                            evidence.append("exact_active_moiety_set_match")
                        elif any(any(are_moieties_equivalent(s, c) for c in candidate_moieties) for s in scanned_moieties):
                            evidence.append("partial_active_moiety_overlap")

                        if scanned.dosage_form == canonical_prod.dosage_form and scanned.dosage_form != DosageForm.UNKNOWN:
                            evidence.append("dosage_form_match")
                        elif scanned.dosage_form != DosageForm.UNKNOWN and canonical_prod.dosage_form != DosageForm.UNKNOWN:
                            conflicts.append("dosage_form_differs")

                        # Check strength equivalence
                        s_strengths = {(s.salt_name, s.strength_value, s.strength_unit) for s in scanned.salts}
                        c_strengths = {(s.salt_name, s.strength_value, s.strength_unit) for s in canonical_prod.salts}
                        if s_strengths and s_strengths == c_strengths:
                            evidence.append("exact_strength_match")
                        elif s_strengths and candidate_moieties.issubset(scanned_moieties):
                            conflicts.append("strength_differs")

                        if scanned.release_type == canonical_prod.release_type and scanned.release_type != ReleaseType.UNKNOWN:
                            evidence.append("release_type_match")
                        elif scanned.release_type != ReleaseType.UNKNOWN and canonical_prod.release_type != ReleaseType.UNKNOWN:
                            conflicts.append("release_type_differs")

                        if prod.is_discontinued:
                            conflicts.append("product_discontinued")
                        if not prod.is_eligible_for_matching:
                            conflicts.append("ineligible_for_exact_match")
                        if prod.is_quarantined:
                            conflicts.append("product_quarantined")

                        # Measure token similarity between scanned query and generic name
                        query_label = scanned.brand_name or scanned.name
                        score = float(fuzz.token_sort_ratio(query_label, prod.name)) / 100.0

                        candidates.append(
                            CandidateRecord(
                                product_id=prod.id,
                                canonical_name=prod.name,
                                retrieval_method="deterministic_salt_match",
                                lexical_score=round(score, 3),
                                evidence=evidence,
                                critical_conflicts=conflicts,
                                requires_confirmation=len(conflicts) > 0,
                                canonical_medicine=canonical_prod,
                            )
                        )
                        seen_ids.add(prod.id)

            # 3. Deterministic Brand Name Lookup (if brand available)
            if scanned.brand_name and len(candidates) < limit:
                normalized_brand = scanned.brand_name.strip().lower()
                brand_records = (
                    session.query(ProductRecord)
                    .filter(
                        ProductRecord.kind == "brand",
                        ProductRecord.is_quarantined == False,
                    )
                    .all()
                )
                for b_rec in brand_records:
                    if b_rec.name.strip().lower() == normalized_brand:
                        # Find generics sharing this brand's salts
                        b_canonical = product_record_to_canonical(b_rec)
                        b_moieties = {s.salt_name for s in b_canonical.salts}
                        if b_moieties:
                            expanded_b_moieties = set()
                            for m in b_moieties:
                                expanded_b_moieties.update(MOIETY_SYNONYMS.get(m, {m}))
                            g_records = (
                                session.query(ProductRecord)
                                .join(ProductSaltRecord)
                                .filter(
                                    ProductRecord.kind == "generic",
                                    ProductRecord.is_quarantined == False,
                                    ProductSaltRecord.salt_name.in_(list(expanded_b_moieties)),
                                )
                                .all()
                            )
                            for g_rec in g_records:
                                if g_rec.id not in seen_ids:
                                    canonical_g = product_record_to_canonical(g_rec)
                                    score = float(fuzz.WRatio(scanned.brand_name, g_rec.name)) / 100.0
                                    candidates.append(
                                        CandidateRecord(
                                            product_id=g_rec.id,
                                            canonical_name=g_rec.name,
                                            retrieval_method="deterministic_brand_lookup",
                                            lexical_score=round(score, 3),
                                            evidence=["brand_resolved_to_salts"],
                                            critical_conflicts=[],
                                            requires_confirmation=False,
                                            canonical_medicine=canonical_g,
                                        )
                                    )
                                    seen_ids.add(g_rec.id)

            # 4. RapidFuzz Lexical Fallback (for spelling variants or noisy scans)
            if len(candidates) < limit:
                query_str = scanned.brand_name or scanned.name
                generic_pool = self._get_generic_pool(session)
                if generic_pool and query_str:
                    choices = [item[1] for item in generic_pool]
                    # Fuzzy match on generic names using WRatio
                    matches = process.extract(
                        query_str,
                        choices,
                        scorer=fuzz.WRatio,
                        limit=limit * 2,
                    )
                    for match_name, score, match_idx in matches:
                        if score >= self.min_fuzzy_score:
                            pid, pname, prod = generic_pool[match_idx]
                            if pid not in seen_ids:
                                canonical_prod = product_record_to_canonical(prod)
                                candidates.append(
                                    CandidateRecord(
                                        product_id=pid,
                                        canonical_name=pname,
                                        retrieval_method="fuzzy_lexical",
                                        lexical_score=round(score / 100.0, 3),
                                        evidence=[f"fuzzy_name_match_{int(score)}%"],
                                        critical_conflicts=[],
                                        requires_confirmation=True,  # Fuzzy candidates require review
                                        canonical_medicine=canonical_prod,
                                    )
                                )
                                seen_ids.add(pid)
                                if len(candidates) >= limit:
                                    break

            # 5. Final Ranking: Deterministic salt matches first, then lexical score descending
            method_priority = {
                "deterministic_salt_match": 0,
                "deterministic_brand_lookup": 1,
                "deterministic_query_match": 1,
                "fuzzy_lexical": 2,
                "fuzzy_brand_lookup": 3,
            }
            candidates.sort(
                key=lambda c: (
                    method_priority.get(c.retrieval_method, 3),
                    0 if "exact_active_moiety_set_match" in c.evidence else 1,
                    0 if "exact_strength_match" in c.evidence else 1,
                    0 if c.canonical_medicine.is_eligible_for_matching else 1,
                    -len(c.evidence),
                    len(c.critical_conflicts),
                    -c.lexical_score,
                )
            )

            candidates = candidates[:limit]

            if not candidates:
                return ResolverResult(
                    status=ResolverStatus.NO_CANDIDATE,
                    query_text=scanned.brand_name or scanned.name,
                    candidates=[],
                    warnings=["No matching or similar generic candidates found in catalogue."],
                )

            return ResolverResult(
                status=ResolverStatus.CANDIDATES_FOUND,
                query_text=scanned.brand_name or scanned.name,
                candidates=candidates,
            )

        finally:
            if close_session:
                session.close()

    def resolve_from_query(
        self,
        query: str,
        session: Optional[Session] = None,
        limit: int = 5,
    ) -> ResolverResult:
        """Resolves candidates from an arbitrary text string (e.g. search typeahead)."""
        if not query or not query.strip():
            return ResolverResult(
                status=ResolverStatus.INSUFFICIENT_EVIDENCE,
                warnings=["Query text is empty."],
            )

        q = query.strip()
        close_session = False
        if session is None:
            session = get_db_session(self.db_url)
            close_session = True

        candidates: List[CandidateRecord] = []
        seen_ids: Set[str] = set()

        try:
            # 1. Exact Name Matching (case-insensitive)
            exact_matches = (
                session.query(ProductRecord)
                .filter(
                    ProductRecord.kind == "generic",
                    ProductRecord.is_quarantined == False,
                    ProductRecord.name.ilike(f"%{q}%"),
                )
                .limit(limit)
                .all()
            )

            for prod in exact_matches:
                canonical_prod = product_record_to_canonical(prod)
                candidates.append(
                    CandidateRecord(
                        product_id=prod.id,
                        canonical_name=prod.name,
                        retrieval_method="deterministic_query_match",
                        lexical_score=1.0,
                        evidence=["substring_match"],
                        critical_conflicts=[],
                        requires_confirmation=False,
                        canonical_medicine=canonical_prod,
                    )
                )
                seen_ids.add(prod.id)

            # 2. Deterministic Brand Name Matching (resolve brand query -> salts -> generics)
            if len(candidates) < limit:
                brand_matches = (
                    session.query(ProductRecord)
                    .filter(
                        ProductRecord.kind == "brand",
                        ProductRecord.is_quarantined == False,
                        ProductRecord.name.ilike(f"%{q}%"),
                    )
                    .all()
                )
                for b_rec in brand_matches:
                    b_salts = {s.salt_name for s in b_rec.salts}
                    if b_salts:
                        expanded_b_salts = set()
                        for m in b_salts:
                            expanded_b_salts.update(MOIETY_SYNONYMS.get(m, {m}))
                        g_matches = (
                            session.query(ProductRecord)
                            .join(ProductSaltRecord)
                            .filter(
                                ProductRecord.kind == "generic",
                                ProductRecord.is_quarantined == False,
                                ProductSaltRecord.salt_name.in_(list(expanded_b_salts)),
                            )
                            .all()
                        )
                        def _rank_g(g: ProductRecord):
                            g_moieties = {s.salt_name for s in g.salts}
                            all_matched = 0 if all(any(are_moieties_equivalent(bm, gm) for gm in g_moieties) for bm in b_salts) else 1
                            form_matched = 0 if (g.dosage_form == b_rec.dosage_form or g.dosage_form in q.lower()) else 1
                            lex = -float(fuzz.token_set_ratio(q, g.name))
                            return (all_matched, form_matched, lex)

                        g_matches.sort(key=_rank_g)
                        for g_prod in g_matches:
                            if g_prod.id not in seen_ids:
                                canonical_g = product_record_to_canonical(g_prod)
                                score = float(fuzz.WRatio(q, b_rec.name)) / 100.0
                                candidates.append(
                                    CandidateRecord(
                                        product_id=g_prod.id,
                                        canonical_name=g_prod.name,
                                        retrieval_method="deterministic_brand_lookup",
                                        lexical_score=round(score, 3),
                                        evidence=[f"resolved_from_brand_{b_rec.name}"],
                                        critical_conflicts=[],
                                        requires_confirmation=False,
                                        canonical_medicine=canonical_g,
                                    )
                                )
                                seen_ids.add(g_prod.id)

            # 3. RapidFuzz Lexical Search on Generic Names (Filtered to drug name tokens)
            q_alpha = re.sub(r"\b\d+\w*\b", "", q).strip()
            if len(q_alpha) >= 3 and len(candidates) < limit:
                generic_pool = self._get_generic_pool(session)
                if generic_pool:
                    choices = [re.sub(r"\b\d+\w*\b", "", item[1]).strip() for item in generic_pool]
                    matches = process.extract(
                        q_alpha,
                        choices,
                        scorer=fuzz.token_set_ratio,
                        limit=limit * 2,
                    )
                    for match_name, score, match_idx in matches:
                        if score >= self.min_fuzzy_score:
                            pid, pname, prod = generic_pool[match_idx]
                            if pid not in seen_ids:
                                canonical_prod = product_record_to_canonical(prod)
                                candidates.append(
                                    CandidateRecord(
                                        product_id=pid,
                                        canonical_name=pname,
                                        retrieval_method="fuzzy_lexical",
                                        lexical_score=round(score / 100.0, 3),
                                        evidence=[f"fuzzy_score_{int(score)}%"],
                                        critical_conflicts=[],
                                        requires_confirmation=True,
                                        canonical_medicine=canonical_prod,
                                    )
                                )
                                seen_ids.add(pid)
                                if len(candidates) >= limit:
                                    break

            # 4. RapidFuzz Lexical Search on Brand Names if still below limit
            if len(candidates) < limit:
                brand_records = (
                    session.query(ProductRecord)
                    .filter(ProductRecord.kind == "brand", ProductRecord.is_quarantined == False)
                    .all()
                )
                if brand_records:
                    brand_choices = [b.name for b in brand_records]
                    brand_fuzzy_matches = process.extract(
                        q,
                        brand_choices,
                        scorer=fuzz.token_set_ratio,
                        limit=3,
                    )
                    for match_brand_name, score, match_idx in brand_fuzzy_matches:
                        if score >= self.min_fuzzy_score:
                            b_rec = brand_records[match_idx]
                            b_salts = {s.salt_name for s in b_rec.salts}
                            if b_salts:
                                expanded_b_salts = set()
                                for m in b_salts:
                                    expanded_b_salts.update(MOIETY_SYNONYMS.get(m, {m}))
                                g_matches = (
                                    session.query(ProductRecord)
                                    .join(ProductSaltRecord)
                                    .filter(
                                        ProductRecord.kind == "generic",
                                        ProductRecord.is_quarantined == False,
                                        ProductSaltRecord.salt_name.in_(list(expanded_b_salts)),
                                    )
                                    .all()
                                )
                                def _rank_gb(g: ProductRecord):
                                    g_moieties = {s.salt_name for s in g.salts}
                                    all_matched = 0 if all(any(are_moieties_equivalent(bm, gm) for gm in g_moieties) for bm in b_salts) else 1
                                    form_matched = 0 if (g.dosage_form == b_rec.dosage_form or g.dosage_form in q.lower()) else 1
                                    lex = -float(fuzz.token_set_ratio(q, g.name))
                                    return (all_matched, form_matched, lex)

                                g_matches.sort(key=_rank_gb)
                                for g_prod in g_matches:
                                    if g_prod.id not in seen_ids:
                                        canonical_g = product_record_to_canonical(g_prod)
                                        candidates.append(
                                            CandidateRecord(
                                                product_id=g_prod.id,
                                                canonical_name=g_prod.name,
                                                retrieval_method="fuzzy_brand_lookup",
                                                lexical_score=round(score / 100.0, 3),
                                                evidence=[f"fuzzy_matched_brand_{b_rec.name}_{int(score)}%"],
                                                critical_conflicts=[],
                                                requires_confirmation=True,
                                                canonical_medicine=canonical_g,
                                            )
                                        )
                                        seen_ids.add(g_prod.id)
                                        if len(candidates) >= limit:
                                            break

            candidates.sort(key=lambda c: -c.lexical_score)
            candidates = candidates[:limit]

            if not candidates:
                return ResolverResult(
                    status=ResolverStatus.NO_CANDIDATE,
                    query_text=q,
                    candidates=[],
                    warnings=["No matching generic products found."],
                )

            return ResolverResult(
                status=ResolverStatus.CANDIDATES_FOUND,
                query_text=q,
                candidates=candidates,
            )

        finally:
            if close_session:
                session.close()

    def resolve_and_match(
        self,
        scanned: CanonicalMedicine,
        workflow_state: ScanWorkflowState = ScanWorkflowState.READY_FOR_MATCHING,
        session: Optional[Session] = None,
        units_per_month: float = 60.0,
        limit: int = 5,
    ) -> Tuple[ResolverResult, MatchResult]:
        """End-to-End Orchestrator: Retrieves candidates and executes Phase 1C Matcher."""
        # Step 1: Candidate Retrieval
        resolver_result = self.resolve_from_canonical(scanned, session=session, limit=limit)

        # Step 2: Convert candidate objects for matcher
        candidate_canonical_list = [c.canonical_medicine for c in resolver_result.candidates]

        # Step 3: Phase 1C Deterministic Matching
        match_result = DeterministicMatcher.match(
            scanned=scanned,
            candidates=candidate_canonical_list,
            workflow_state=workflow_state,
            units_per_month=units_per_month,
        )

        return (resolver_result, match_result)

    def resolve_and_match_extraction(
        self,
        extraction: RawMedicineExtraction,
        session: Optional[Session] = None,
        units_per_month: float = 60.0,
        limit: int = 5,
    ) -> Tuple[ScanWorkflowState, Optional[ResolverResult], MatchResult]:
        """Integrates perception extraction with CandidateResolver and Phase 1C Matcher.
        
        Enforces:
        1. can_authorize_exact_matching and has_critical_conflicts gates.
        2. Non-ready states (NEEDS_USER_CONFIRMATION, EXTRACTION_INCOMPLETE, REJECT_IMAGE)
           fail closed with MatchTier.NONE and zero savings.
        """
        from ml.vision.reconciliation import extraction_to_canonical

        scanned_canonical, workflow_state, reasons = extraction_to_canonical(extraction)

        if (
            workflow_state != ScanWorkflowState.READY_FOR_MATCHING
            or scanned_canonical is None
            or scanned_canonical.is_quarantined
        ):
            # Immediate fail-closed abort: zero candidates, zero savings, tier NONE
            match_result = MatchResult(
                tier=MatchTier.NONE,
                workflow_state=workflow_state,
                scanned_product_id=scanned_canonical.product_id if scanned_canonical else "unidentified",
                matched_alternatives=[],
                warnings=reasons or [f"Workflow state '{workflow_state.value}' blocks matching."],
                disclaimer=MANDATORY_DISCLAIMER,
            )
            return (workflow_state, None, match_result)

        # Standard resolution and deterministic matching
        resolver_result, match_result = self.resolve_and_match(
            scanned=scanned_canonical,
            workflow_state=workflow_state,
            session=session,
            units_per_month=units_per_month,
            limit=limit,
        )
        return (workflow_state, resolver_result, match_result)
