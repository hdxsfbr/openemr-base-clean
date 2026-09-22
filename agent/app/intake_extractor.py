"""Bounded document extraction worker for lab reports and intake forms.

Only opaque versioned references cross the worker boundary. Protected source
bytes, OCR text, proposed facts, and evidence stay behind injected storage and
system-processing ports.
"""

from __future__ import annotations

import hashlib
import copy
import time
from concurrent.futures import Executor, ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Mapping, Protocol

from .contracts.week2 import (
    IntakeExtractionEnvelope,
    LabExtractionEnvelope,
    NormalizedBox,
    OcrPage,
    SourceDocumentRef,
    StageTiming,
    VersionedReference,
    WorkerHandoffRequest,
    WorkerHandoffResult,
)

ExtractionEnvelope = LabExtractionEnvelope | IntakeExtractionEnvelope
PIPELINE_DEADLINE_SECONDS = 95.0
FIRST_ATTEMPT_SECONDS = 60.0
REGION_RETRY_SECONDS = 30.0
REGION_RETRY_BACKOFF_SECONDS = 0.5


class DocumentPipelineTimeout(Exception):
    """A dependency did not complete inside the extraction deadline."""


class DocumentCanceled(Exception):
    """The durable job was canceled before its terminal extraction was saved."""


class MalformedDocument(Exception):
    """The protected source cannot be safely rendered as its declared type."""


class UnreadableDocument(Exception):
    """Rendering succeeded but deterministic OCR recovered no document text."""


class ExtractionDependencyUnavailable(Exception):
    """A protected renderer, OCR, model, source, or ledger dependency is down."""


class SourceVersionMismatch(Exception):
    """The loaded source identity, version, or content differs from the handoff."""


@dataclass(frozen=True)
class AuthorizedSourceVersion:
    """One exact source version returned by the authorized document gateway."""

    source: SourceDocumentRef
    version: str
    content: bytes


@dataclass(frozen=True)
class RenderedPage:
    page_number: int
    pixels: bytes
    rendered_page_sha256: str
    renderer_version: str
    preprocessing_version: str
    orientation_degrees: int
    source_orientation_degrees: int = 0


@dataclass(frozen=True)
class ExtractionUsage:
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_microusd: int = 0

    def __add__(self, other: "ExtractionUsage") -> "ExtractionUsage":
        return ExtractionUsage(
            model_calls=self.model_calls + other.model_calls,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cost_microusd=self.cost_microusd + other.cost_microusd,
        )


@dataclass(frozen=True)
class ExtractionDraft:
    payload: Mapping[str, object]
    ambiguous_regions: tuple["BoundedRegion", ...] = ()
    usage: ExtractionUsage = field(default_factory=ExtractionUsage)


@dataclass(frozen=True)
class BoundedRegion:
    field_id: str
    page_number: int
    box: NormalizedBox

    def __post_init__(self) -> None:
        object.__setattr__(self, "box", NormalizedBox.model_validate(self.box))


@dataclass(frozen=True)
class RegionCrop:
    region: BoundedRegion
    pixels: bytes
    content_sha256: str


@dataclass(frozen=True)
class ExtractionIdentity:
    extraction_id: str
    extraction_version: int


@dataclass(frozen=True)
class StoredExtractionTerminal:
    status: Literal["completed", "partial", "unavailable", "failed", "canceled"]
    output_refs: tuple[VersionedReference, ...]
    limitation_codes: tuple[str, ...]
    retryable: bool


@dataclass(frozen=True)
class ExtractionDependencyReadiness:
    name: str
    ok: bool
    detail: Literal["ready", "unavailable", "not_configured", "timeout"]


@dataclass(frozen=True)
class ExtractionCapabilityReadiness:
    ok: bool
    dependencies: tuple[ExtractionDependencyReadiness, ...]


@dataclass(frozen=True)
class ExtractionTelemetryEvent:
    handoff_id: str
    correlation_id: str
    route: Literal["intake_extractor"]
    status: Literal["completed", "partial", "unavailable", "failed", "canceled"]
    document_type: Literal["lab_report", "intake_form"] | None
    attempt: int
    page_count: int
    region_retry_count: int
    model_calls: int
    input_tokens: int
    output_tokens: int
    cost_microusd: int
    duration_ms: int


class SourceDocumentPort(Protocol):
    def load_authorized(self, reference: VersionedReference) -> AuthorizedSourceVersion: ...


class ExtractionStorePort(Protocol):
    def find_terminal(self, handoff_id: str) -> StoredExtractionTerminal | None: ...

    def allocate_identity(self, handoff_id: str, source_document_id: str) -> ExtractionIdentity: ...

    def save_once(self, handoff_id: str, extraction: ExtractionEnvelope) -> VersionedReference: ...


class RendererPort(Protocol):
    def render(self, source: AuthorizedSourceVersion) -> list[RenderedPage]: ...

    def crop(self, page: RenderedPage, region: BoundedRegion) -> RegionCrop: ...


class OcrPort(Protocol):
    def recognize(self, pages: list[RenderedPage]) -> list[object]: ...


class ProposalExtractorPort(Protocol):
    def extract(
        self,
        document_type: str,
        ocr_pages: list[OcrPage],
        *,
        timeout_seconds: float,
    ) -> ExtractionDraft: ...

    def refine(
        self,
        document_type: str,
        crops: tuple[RegionCrop, ...],
        draft: ExtractionDraft,
        *,
        timeout_seconds: float,
    ) -> ExtractionDraft: ...


class CancellationPort(Protocol):
    def is_cancelled(self, handoff_id: str) -> bool: ...


class ReadinessProbePort(Protocol):
    def ready(self) -> bool: ...


class ExtractionTelemetryPort(Protocol):
    def record(self, event: ExtractionTelemetryEvent) -> None: ...


class NeverCanceled:
    def is_cancelled(self, handoff_id: str) -> bool:
        return False


class NoopExtractionTelemetry:
    def record(self, event: ExtractionTelemetryEvent) -> None:
        return None


class IntakeExtractorWorker:
    """Create one immutable extraction attempt from one authorized source version."""

    def __init__(
        self,
        *,
        source_store: SourceDocumentPort,
        extraction_store: ExtractionStorePort,
        renderer: RendererPort,
        ocr: OcrPort,
        extractor: ProposalExtractorPort,
        monotonic=time.monotonic,
        sleep=time.sleep,
        executor: Executor | None = None,
        cancellation: CancellationPort | None = None,
        readiness_probes: Mapping[str, ReadinessProbePort] | None = None,
        telemetry: ExtractionTelemetryPort | None = None,
    ) -> None:
        self._source_store = source_store
        self._extraction_store = extraction_store
        self._renderer = renderer
        self._ocr = ocr
        self._extractor = extractor
        self._monotonic = monotonic
        self._sleep = sleep
        self._executor = executor or ThreadPoolExecutor(max_workers=4, thread_name_prefix="document-extraction")
        self._cancellation = cancellation or NeverCanceled()
        self._readiness_probes = dict(readiness_probes or {})
        self._telemetry = telemetry or NoopExtractionTelemetry()

    def readiness(self) -> ExtractionCapabilityReadiness:
        dependencies: list[ExtractionDependencyReadiness] = []
        for name in ("extraction_store", "ocr", "region_extractor", "renderer", "source_store"):
            probe = self._readiness_probes.get(name)
            if probe is None:
                dependencies.append(ExtractionDependencyReadiness(name, False, "not_configured"))
                continue
            future = self._executor.submit(probe.ready)
            try:
                ready = bool(future.result(timeout=2.0))
            except FutureTimeout:
                future.cancel()
                dependencies.append(ExtractionDependencyReadiness(name, False, "timeout"))
            except Exception:
                dependencies.append(ExtractionDependencyReadiness(name, False, "unavailable"))
            else:
                dependencies.append(
                    ExtractionDependencyReadiness(name, ready, "ready" if ready else "unavailable")
                )
        return ExtractionCapabilityReadiness(
            ok=all(dependency.ok for dependency in dependencies),
            dependencies=tuple(dependencies),
        )

    def run(self, handoff: WorkerHandoffRequest, *, now: str) -> WorkerHandoffResult:
        started = self._monotonic()
        pipeline_budget = min(
            PIPELINE_DEADLINE_SECONDS,
            max(0.0, (_utc(handoff.deadline_at) - _utc(now)).total_seconds()),
        )
        source_refs = [reference for reference in handoff.input_refs if reference.kind == "source_document"]
        if handoff.worker != "intake_extractor" or len(source_refs) != 1 or len(handoff.input_refs) != 1:
            return self._result(handoff, started, "failed", [], ["document_handoff_invalid"], False)

        source_ref = source_refs[0]
        try:
            self._check_canceled(handoff.handoff_id)
            authorized = self._run_bounded(
                lambda: self._source_store.load_authorized(source_ref),
                started,
                pipeline_budget,
            )
            self._check_canceled(handoff.handoff_id)
            self._validate_source_reference(source_ref, authorized)
            terminal = self._run_bounded(
                lambda: self._extraction_store.find_terminal(handoff.handoff_id),
                started,
                pipeline_budget,
            )
            if terminal is not None:
                return self._result(
                    handoff,
                    started,
                    terminal.status,
                    list(terminal.output_refs),
                    list(terminal.limitation_codes),
                    terminal.retryable,
                )
            rendered = self._run_bounded(
                lambda: self._renderer.render(authorized),
                started,
                pipeline_budget,
            )
            self._check_canceled(handoff.handoff_id)
            self._validate_rendered_pages(rendered, authorized.source)
            raw_ocr_pages = self._run_bounded(
                lambda: self._ocr.recognize(rendered),
                started,
                pipeline_budget,
            )
            self._check_canceled(handoff.handoff_id)
            ocr_pages = [OcrPage.model_validate(page) for page in raw_ocr_pages]
            self._validate_ocr_pages(ocr_pages, rendered, authorized.source)
            if not any(page.text.strip() for page in ocr_pages):
                raise UnreadableDocument
            first_budget = min(FIRST_ATTEMPT_SECONDS, self._remaining(started, pipeline_budget))
            draft = self._run_bounded(
                lambda: self._extractor.extract(
                    authorized.source.document_type,
                    ocr_pages,
                    timeout_seconds=first_budget,
                ),
                started,
                pipeline_budget,
                stage_budget=first_budget,
            )
            self._check_canceled(handoff.handoff_id)
            usage = draft.usage
            region_retry_count = 0
            if draft.ambiguous_regions:
                region_retry_count = 1
                crops = self._bounded_crops(rendered, draft.ambiguous_regions)
                if self._remaining(started, pipeline_budget) <= REGION_RETRY_BACKOFF_SECONDS:
                    raise DocumentPipelineTimeout
                self._sleep(REGION_RETRY_BACKOFF_SECONDS)
                retry_budget = min(REGION_RETRY_SECONDS, self._remaining(started, pipeline_budget))
                refined = self._run_bounded(
                    lambda: self._extractor.refine(
                        authorized.source.document_type,
                        crops,
                        draft,
                        timeout_seconds=retry_budget,
                    ),
                    started,
                    pipeline_budget,
                    stage_budget=retry_budget,
                )
                usage = usage + refined.usage
                draft = refined
                self._check_canceled(handoff.handoff_id)
            payload, review_required = self._normalize_payload(draft.payload)
            identity = self._extraction_store.allocate_identity(
                handoff.handoff_id,
                authorized.source.source_document_id,
            )
            envelope_type = (
                LabExtractionEnvelope
                if authorized.source.document_type == "lab_report"
                else IntakeExtractionEnvelope
            )
            envelope = envelope_type.model_validate({
                "extraction_id": identity.extraction_id,
                "extraction_version": identity.extraction_version,
                "schema_name": "lab-report" if authorized.source.document_type == "lab_report" else "intake-form",
                "schema_version": "1.0.0",
                "source": authorized.source.model_dump(mode="json"),
                "state": "review_required" if review_required else "schema_valid",
                "created_at": now,
                "ocr_pages": [page.model_dump(mode="json") for page in ocr_pages],
                "payload": payload,
            })
            self._validate_exact_quotes(envelope)
            output_ref = self._run_bounded(
                lambda: self._extraction_store.save_once(handoff.handoff_id, envelope),
                started,
                pipeline_budget,
            )
        except MalformedDocument:
            return self._result(handoff, started, "failed", [], ["document_malformed"], False)
        except UnreadableDocument:
            return self._result(handoff, started, "unavailable", [], ["document_unreadable"], False)
        except ExtractionDependencyUnavailable:
            return self._result(
                handoff,
                started,
                "unavailable",
                [],
                ["document_extraction_unavailable"],
                True,
            )
        except SourceVersionMismatch:
            return self._result(handoff, started, "failed", [], ["document_source_mismatch"], False)
        except DocumentCanceled:
            return self._result(handoff, started, "canceled", [], ["document_canceled"], False)
        except DocumentPipelineTimeout:
            return self._result(handoff, started, "unavailable", [], ["document_timeout"], True)
        except Exception:
            return self._result(handoff, started, "failed", [], ["document_extraction_invalid"], False)

        if review_required:
            return self._result(
                handoff,
                started,
                "partial",
                [output_ref],
                ["document_review_required"],
                False,
                document_type=authorized.source.document_type,
                page_count=authorized.source.page_count,
                region_retry_count=region_retry_count,
                usage=usage,
            )
        return self._result(
            handoff,
            started,
            "completed",
            [output_ref],
            [],
            False,
            document_type=authorized.source.document_type,
            page_count=authorized.source.page_count,
            region_retry_count=region_retry_count,
            usage=usage,
        )

    def _check_canceled(self, handoff_id: str) -> None:
        if self._cancellation.is_cancelled(handoff_id):
            raise DocumentCanceled

    def _remaining(self, started: float, pipeline_budget: float) -> float:
        return max(0.0, pipeline_budget - (self._monotonic() - started))

    def _run_bounded(
        self,
        operation,
        started: float,
        pipeline_budget: float,
        *,
        stage_budget: float | None = None,
    ):
        timeout = self._remaining(started, pipeline_budget)
        if stage_budget is not None:
            timeout = min(timeout, stage_budget)
        if timeout <= 0:
            raise DocumentPipelineTimeout
        future = self._executor.submit(operation)
        try:
            return future.result(timeout=timeout)
        except FutureTimeout as exc:
            future.cancel()
            raise DocumentPipelineTimeout from exc

    def _bounded_crops(
        self,
        rendered_pages: list[RenderedPage],
        regions: tuple[BoundedRegion, ...],
    ) -> tuple[RegionCrop, ...]:
        if not 1 <= len(regions) <= 20:
            raise ValueError("region retry requires one to twenty bounded regions")
        pages = {page.page_number: page for page in rendered_pages}
        crops: list[RegionCrop] = []
        for region in regions:
            page = pages.get(region.page_number)
            if page is None:
                raise ValueError("region retry points outside rendered pages")
            crop = self._renderer.crop(page, region)
            if crop.region != region or hashlib.sha256(crop.pixels).hexdigest() != crop.content_sha256:
                raise ValueError("region crop integrity mismatch")
            crops.append(crop)
        return tuple(crops)

    @staticmethod
    def _normalize_payload(payload: Mapping[str, object]) -> tuple[dict[str, object], bool]:
        normalized = copy.deepcopy(dict(payload))
        review_required = False

        def visit(value: object) -> None:
            nonlocal review_required
            if isinstance(value, dict):
                if {"field_id", "value", "state", "evidence"} <= value.keys():
                    diagnostics = {
                        code
                        for evidence in value["evidence"]
                        for code in evidence.get("validation", [])
                    }
                    if diagnostics - {"valid"}:
                        value["state"] = "review_required"
                    if value["state"] != "schema_valid":
                        review_required = True
                for nested in value.values():
                    visit(nested)
            elif isinstance(value, list):
                for nested in value:
                    visit(nested)

        visit(normalized)
        return normalized, review_required

    @staticmethod
    def _validate_source_reference(reference: VersionedReference, source: AuthorizedSourceVersion) -> None:
        if reference.id != source.source.source_document_id or reference.version != source.version:
            raise SourceVersionMismatch
        content_hash = hashlib.sha256(source.content).hexdigest()
        if content_hash != source.source.content_sha256 or reference.integrity_sha256 != content_hash:
            raise SourceVersionMismatch

    @staticmethod
    def _validate_rendered_pages(pages: list[RenderedPage], source: SourceDocumentRef) -> None:
        if [page.page_number for page in pages] != list(range(1, source.page_count + 1)):
            raise ValueError("rendered pages must exactly match the source page sequence")
        for page in pages:
            if page.source_orientation_degrees not in (0, 90, 180, 270):
                raise ValueError("source orientation must be a right-angle rotation")
            if page.orientation_degrees != 0:
                raise ValueError("rendered pages must have normalized orientation")
            if hashlib.sha256(page.pixels).hexdigest() != page.rendered_page_sha256:
                raise ValueError("rendered page integrity mismatch")

    @staticmethod
    def _validate_ocr_pages(
        ocr_pages: list[OcrPage],
        rendered_pages: list[RenderedPage],
        source: SourceDocumentRef,
    ) -> None:
        if len(ocr_pages) != source.page_count:
            raise ValueError("OCR pages must exactly match the source page count")
        for ocr_page, rendered_page in zip(ocr_pages, rendered_pages, strict=True):
            if (
                ocr_page.page_number != rendered_page.page_number
                or ocr_page.rendered_page_sha256 != rendered_page.rendered_page_sha256
                or ocr_page.renderer_version != rendered_page.renderer_version
                or ocr_page.preprocessing_version != rendered_page.preprocessing_version
            ):
                raise ValueError("OCR provenance does not match the rendered page")

    @staticmethod
    def _validate_exact_quotes(envelope: ExtractionEnvelope) -> None:
        pages = {page.page_number: page for page in envelope.ocr_pages}
        payload = envelope.payload.model_dump(mode="python")

        def visit(value: object) -> None:
            if isinstance(value, dict):
                if {"field_id", "value", "state", "evidence"} <= value.keys():
                    for evidence in value["evidence"]:
                        page = pages[evidence["page_number"]]
                        quote = page.text[evidence["ocr_span_start"] : evidence["ocr_span_end"]]
                        if evidence["printed_quote"] != quote:
                            raise ValueError("field evidence quote does not match retained OCR")
                for nested in value.values():
                    visit(nested)
            elif isinstance(value, list):
                for nested in value:
                    visit(nested)

        visit(payload)

    def _result(
        self,
        handoff: WorkerHandoffRequest,
        started: float,
        status: Literal["completed", "partial", "unavailable", "failed", "canceled"],
        output_refs: list[VersionedReference],
        limitation_codes: list[str],
        retryable: bool,
        *,
        document_type: Literal["lab_report", "intake_form"] | None = None,
        page_count: int = 0,
        region_retry_count: int = 0,
        usage: ExtractionUsage | None = None,
    ) -> WorkerHandoffResult:
        duration_ms = max(0, round((self._monotonic() - started) * 1000))
        usage = usage or ExtractionUsage()
        outcome = (
            "completed"
            if status == "completed"
            else "limited"
            if status == "partial"
            else "canceled"
            if status == "canceled"
            else "failed"
        )
        result = WorkerHandoffResult.model_validate({
            "handoff_id": handoff.handoff_id,
            "correlation_id": handoff.correlation_id,
            "conversation_id": handoff.conversation_id,
            "turn_id": handoff.turn_id,
            "event_kind": handoff.event_kind,
            "worker": handoff.worker,
            "attempt": handoff.attempt,
            "status": status,
            "output_refs": [reference.model_dump(mode="json") for reference in output_refs],
            "limitation_codes": limitation_codes,
            "retryable": retryable,
            "stage_timings": [StageTiming(
                stage="document_extraction",
                duration_ms=duration_ms,
                outcome=outcome,
            ).model_dump(mode="json")],
            "contract_versions": handoff.contract_versions,
        })
        try:
            self._telemetry.record(ExtractionTelemetryEvent(
                handoff_id=handoff.handoff_id,
                correlation_id=handoff.correlation_id,
                route="intake_extractor",
                status=status,
                document_type=document_type,
                attempt=handoff.attempt,
                page_count=page_count,
                region_retry_count=region_retry_count,
                model_calls=usage.model_calls,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cost_microusd=usage.cost_microusd,
                duration_ms=duration_ms,
            ))
        except Exception:
            pass
        return result


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return parsed.astimezone(timezone.utc)
