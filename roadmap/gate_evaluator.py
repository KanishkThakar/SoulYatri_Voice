"""Gate evaluation decision logic for the speech-native voice roadmap.

The :class:`GateEvaluator` is the central decision-logic component for both
Decision_Gates and Launch_Gates (see the "Gate Evaluator" section of
``design.md``). It is a *pure* function of its inputs — a :class:`Gate`
definition, a dict of measured values keyed by ``metric_name``, and the current
:class:`~roadmap.licensing.LicensingRegister` state — and never depends on
hidden state (design note: ``GateResult.overall_passed`` is a pure function of
``criteria_results`` and the Licensing_Register).

Evaluation rules (Requirements 1.4, 1.5, 8.4, 8.5, 11.5, 11.7)
--------------------------------------------------------------
1. **Per-criterion resolution.** Every criterion in the gate's
   ``exit_criteria`` resolves to exactly one pass/fail result by applying its
   comparison ``operator`` (``<=``, ``<``, ``>=``, ``>``, ``==``) to the
   measured value against the threshold (Requirements 1.4, 8.4).
2. **Fail-closed on missing measurements.** A criterion whose ``metric_name``
   is absent from ``measured_values`` resolves to **fail**; there is no way for
   an unmeasured criterion to pass. For the resulting :class:`CriterionResult`
   the ``measured`` field is recorded as ``float("nan")`` — the documented
   sentinel for "no value was provided" — and ``passed`` is ``False``.
3. **Overall pass rule.** ``overall_passed`` is ``True`` **iff** every criterion
   passes **and** the Licensing_Register contains no unresolved compliance
   warning **and** no adopted component whose license prohibits its intended use
   (Requirements 11.5, 11.7). A ``None`` registry is treated as a clean register
   (no warnings, no prohibiting licenses).
4. **Blocking + remediation.** When the gate does not pass, ``blocked`` is set
   to ``True`` and ``remediation`` carries one entry per failing criterion
   naming the criterion and its corrective action (Requirements 8.5). When the
   block is (also) caused by the Licensing_Register — an unresolved warning or a
   prohibiting license — a dedicated remediation entry is appended for that
   licensing issue (Requirement 11.7).
5. **Decision-gate owner/fallback.** A Decision_Gate (``gate.kind ==
   "decision"``) additionally exposes exactly one named owner role and a
   fallback action used when the exit criteria are not met — for ``G1`` the
   fallback is the explicitly allowed "remain on LEAN_Track" (Requirements 1.4,
   1.5). See :class:`DecisionGateResult` for how this is surfaced.

How the decision-gate owner/fallback is surfaced
------------------------------------------------
The canonical :class:`~roadmap.models.selection.GateResult` model intentionally
carries only the criterion/overall/blocking fields and has no owner/fallback
slot. Rather than mutate that shared model, this module defines a thin
:class:`DecisionGateResult` wrapper that *composes* a ``GateResult`` with the
gate's ``owner_role`` and ``fallback_action``. :meth:`GateEvaluator.evaluate`
returns a plain ``GateResult`` for any gate; :meth:`GateEvaluator.
evaluate_decision_gate` returns a ``DecisionGateResult`` and is the entry point
when the caller needs the owner/fallback alongside the result. This keeps the
serializable planning model stable while still exposing the decision-gate
specifics required by Requirements 1.4/1.5.

This module performs no I/O and no GPU/training work; it is pure decision logic
operating on the dataclasses in ``roadmap/models/``.

Requirements: 1.4, 1.5, 8.4, 8.5, 11.5, 11.7.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Mapping, Optional

from .licensing import LicensingRegister
from .models.phases import OPERATOR_VALUES, Gate, GateCriterion
from .models.selection import CriterionResult, GateResult

__all__ = [
    "MISSING_MEASUREMENT",
    "DecisionGateResult",
    "GateEvaluator",
]

#: Sentinel recorded in ``CriterionResult.measured`` when a criterion's metric
#: is absent from the supplied measured values. ``float("nan")`` is used so the
#: result is still a valid ``float`` while being unambiguously "not a real
#: measurement" (any comparison against it is ``False``, reinforcing the
#: fail-closed semantics). Callers/reporters should treat a NaN ``measured`` as
#: "no value provided".
MISSING_MEASUREMENT: float = float("nan")


#: Maps each supported operator symbol to the comparison that returns ``True``
#: when the measured value *satisfies* the criterion. Every comparison with a
#: NaN operand is ``False`` in Python, so a missing/NaN measurement naturally
#: resolves to fail without a special case here.
_OPERATORS: dict[str, Callable[[float, float], bool]] = {
    "<=": lambda measured, threshold: measured <= threshold,
    "<": lambda measured, threshold: measured < threshold,
    ">=": lambda measured, threshold: measured >= threshold,
    ">": lambda measured, threshold: measured > threshold,
    "==": lambda measured, threshold: measured == threshold,
}


@dataclass
class DecisionGateResult:
    """A :class:`GateResult` paired with a Decision_Gate's owner and fallback.

    Composes the canonical, serializable ``GateResult`` with the two
    decision-gate-specific fields the design requires a gate evaluation to
    surface (Requirements 1.4, 1.5):

    Attributes:
        result: The underlying :class:`GateResult` (per-criterion results,
            overall pass/fail, blocked flag, and remediation list).
        owner_role: The single named role responsible for the gate decision,
            taken from ``Gate.owner_role`` (Requirement 1.4).
        fallback_action: The action to take when the exit criteria are not met,
            taken from ``Gate.fallback_action`` — e.g. "remain on LEAN_Track"
            (Requirement 1.5). It is the caller's signal for what to do when
            ``result.overall_passed`` is ``False``.
    """

    result: GateResult
    owner_role: str
    fallback_action: str


class GateEvaluator:
    """Evaluate a Decision_Gate or Launch_Gate against measured values.

    Stateless: every method is a pure function of its arguments. The same gate,
    measured values, and registry state always yield an equal result.
    """

    def evaluate(
        self,
        gate: Gate,
        measured_values: Mapping[str, float],
        registry: Optional[LicensingRegister] = None,
    ) -> GateResult:
        """Evaluate ``gate`` and return a :class:`GateResult`.

        Resolves every criterion in ``gate.exit_criteria`` to a single pass/fail
        result, computes ``overall_passed`` (criteria + licensing), and, when
        the gate does not pass, sets ``blocked`` and builds the per-failure
        remediation list.

        Args:
            gate: The gate definition to evaluate. Its ``exit_criteria`` are the
                criteria resolved here.
            measured_values: Mapping of ``metric_name`` to measured value. A
                metric absent from this mapping resolves its criterion to fail
                (fail-closed) with a ``float("nan")`` measured sentinel.
            registry: The current Licensing_Register state, or ``None`` to treat
                the register as clean. ``overall_passed`` additionally requires
                the register to have no unresolved compliance warning and no
                adopted component whose license prohibits its intended use
                (Requirements 11.5, 11.7).

        Returns:
            A :class:`GateResult` with one :class:`CriterionResult` per exit
            criterion, the overall pass/fail, the blocked flag, and remediation
            entries (one per failing criterion, plus a licensing entry when the
            register blocks the gate).
        """
        criteria_results = [
            self._evaluate_criterion(criterion, measured_values)
            for criterion in gate.exit_criteria
        ]

        all_criteria_passed = all(r.passed for r in criteria_results)
        licensing_clean = self._licensing_clean(registry)
        overall_passed = all_criteria_passed and licensing_clean

        remediation: list[str] = []
        if not overall_passed:
            remediation.extend(
                self._criterion_remediation(r)
                for r in criteria_results
                if not r.passed
            )
            remediation.extend(self._licensing_remediation(registry))

        return GateResult(
            gate_id=gate.id,
            criteria_results=criteria_results,
            overall_passed=overall_passed,
            blocked=not overall_passed,
            remediation=remediation,
        )

    def evaluate_decision_gate(
        self,
        gate: Gate,
        measured_values: Mapping[str, float],
        registry: Optional[LicensingRegister] = None,
    ) -> DecisionGateResult:
        """Evaluate a Decision_Gate, exposing its owner role and fallback action.

        Runs the same evaluation as :meth:`evaluate` and wraps the resulting
        :class:`GateResult` in a :class:`DecisionGateResult` that also carries
        the gate's single ``owner_role`` and ``fallback_action`` (Requirements
        1.4, 1.5). The fallback — e.g. "remain on LEAN_Track" — is what the
        caller applies when ``result.overall_passed`` is ``False``.

        Args:
            gate: The Decision_Gate to evaluate. Must have ``kind ==
                "decision"``.
            measured_values: Mapping of ``metric_name`` to measured value
                (fail-closed on missing metrics, as in :meth:`evaluate`).
            registry: The current Licensing_Register state, or ``None`` for a
                clean register.

        Returns:
            A :class:`DecisionGateResult` composing the ``GateResult`` with the
            gate's ``owner_role`` and ``fallback_action``.

        Raises:
            ValueError: If ``gate.kind`` is not ``"decision"``.
        """
        if gate.kind != "decision":
            raise ValueError(
                "evaluate_decision_gate requires a decision gate, got "
                f"kind={gate.kind!r}; use evaluate() for launch gates"
            )

        result = self.evaluate(gate, measured_values, registry)
        return DecisionGateResult(
            result=result,
            owner_role=gate.owner_role,
            fallback_action=gate.fallback_action,
        )

    # -- Internals -----------------------------------------------------------

    @staticmethod
    def _evaluate_criterion(
        criterion: GateCriterion,
        measured_values: Mapping[str, float],
    ) -> CriterionResult:
        """Resolve a single criterion to one pass/fail :class:`CriterionResult`.

        A metric absent from ``measured_values`` resolves to fail with the
        ``MISSING_MEASUREMENT`` (NaN) sentinel; otherwise the criterion's
        operator decides the outcome (Requirements 1.4, 8.4).
        """
        if criterion.metric_name in measured_values:
            measured = float(measured_values[criterion.metric_name])
            passed = GateEvaluator._satisfies(
                measured, criterion.operator, criterion.threshold
            )
        else:
            # Fail-closed: no measured value provided for this metric.
            measured = MISSING_MEASUREMENT
            passed = False

        return CriterionResult(
            metric_name=criterion.metric_name,
            measured=measured,
            threshold=criterion.threshold,
            operator=criterion.operator,
            passed=passed,
        )

    @staticmethod
    def _satisfies(measured: float, operator: str, threshold: float) -> bool:
        """Return whether ``measured`` satisfies ``operator`` vs ``threshold``."""
        try:
            compare = _OPERATORS[operator]
        except KeyError:  # pragma: no cover - guarded by GateCriterion validation
            raise ValueError(
                f"operator must be one of {OPERATOR_VALUES}, got {operator!r}"
            ) from None
        return compare(measured, threshold)

    @staticmethod
    def _licensing_clean(registry: Optional[LicensingRegister]) -> bool:
        """Return whether the register permits a pass (clean when ``None``).

        Clean means: no unresolved compliance warning and no adopted component
        whose license prohibits its intended use (Requirements 11.5, 11.7).
        """
        if registry is None:
            return True
        return not registry.has_unresolved_warnings() and not registry.has_prohibiting_license()

    @staticmethod
    def _criterion_remediation(result: CriterionResult) -> str:
        """Build the remediation entry for a single failing criterion (8.5)."""
        if math.isnan(result.measured):
            return (
                f"{result.metric_name}: no measured value provided (fail-closed). "
                f"Measure and record {result.metric_name} so that it satisfies "
                f"{result.operator} {result.threshold}."
            )
        return (
            f"{result.metric_name}: measured {result.measured} does not satisfy "
            f"{result.operator} {result.threshold}. Remediate {result.metric_name} "
            f"until it satisfies {result.operator} {result.threshold}."
        )

    @staticmethod
    def _licensing_remediation(registry: Optional[LicensingRegister]) -> list[str]:
        """Build remediation entries for any licensing-caused block (11.7).

        Returns at most two entries: one for unresolved compliance warnings and
        one for adopted components whose license prohibits intended use. Returns
        an empty list when the register is ``None`` or clean.
        """
        if registry is None:
            return []

        entries: list[str] = []

        if registry.has_unresolved_warnings():
            names = ", ".join(
                sorted(w.component_name for w in registry.unresolved_warnings())
            )
            entries.append(
                "Licensing: resolve the unresolved compliance warning(s) for "
                f"[{names}] by recording a recognized open-source license "
                "identifier before this gate can pass."
            )

        if registry.has_prohibiting_license():
            names = ", ".join(
                sorted(
                    e.component_name
                    for e in registry.entries()
                    if not e.intended_use_permitted
                )
            )
            entries.append(
                "Licensing: an adopted component's license prohibits its "
                f"intended use [{names}]. Remove, replace, or relicense it "
                "before this gate can pass."
            )

        return entries
