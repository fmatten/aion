# SPDX-License-Identifier: EUPL-1.2
# Copyright © Friedhelm Matten, ISCaD GmbH, 30900 Wedemark
# AION — Algebraic Interval Ontology for Clinical Networks
"""
aion.query.patterns
===================
AION §11: Temporal Pattern Languages.

RTPPattern — Regular Temporal Patterns over event alphabet Σ_T.
Grammar:
    Atom         : (type, attr_pred?)            matches a single event
    Concat       : π_1 →[r] π_2                 Allen relation r between matches
    Alternate    : π_1 | π_2                    either branch matches
    KleeneStar   : π*                           zero or more matches
    Option       : π?                           zero or one match
    Repetition   : π{m,n}                       m to n matches

Match(π, p_k) → list of matching event tuples (subsequences of e_k).

TCFG — Temporal Context-Free Grammars (AION §11.4).
Implements a simplified CYK-style parsing for nested structures.

PatternFrequency, PatternConfidence (AION §11.5) for statistical analysis.
"""

from __future__ import annotations

import re as _re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..core.allen import AllenRelation, holds
from ..core.event import ClinicalEvent, EventSet
from ..core.types import TypeHierarchy, default_hierarchy
from .predicates import QueryContext


# ── Type aliases ──────────────────────────────────────────────────────────────

Match = list[ClinicalEvent]           # a single pattern match
MatchList = list[Match]               # all matches of a pattern


# ── RTPAtom ───────────────────────────────────────────────────────────────────

@dataclass
class RTPAtom:
    """
    AION §11.2 (1): Atom (τ, θ).
    Matches event e with type(e) ≺* τ and θ(α(e)) = True.
    """
    type_name:   str
    attr_pred:   Optional[Callable[[ClinicalEvent], bool]] = None
    label:       str = ""

    def matches_event(
        self, event: ClinicalEvent, h: TypeHierarchy
    ) -> bool:
        if not h.is_subtype(event.type, self.type_name):
            return False
        if self.attr_pred and not self.attr_pred(event):
            return False
        return True

    def __repr__(self) -> str:
        s = self.label or self.type_name
        return f"({s})"


# ── RTP Pattern classes ───────────────────────────────────────────────────────

class RTPPattern:
    """Base class for all RTP pattern nodes."""

    def match(
        self,
        sequence: list[ClinicalEvent],
        h: TypeHierarchy,
        start_idx: int = 0,
    ) -> MatchList:
        """
        Try to match *self* against *sequence* starting at *start_idx*.
        Returns all possible matches (each match = list of events consumed).
        """
        raise NotImplementedError

    def match_all(
        self,
        sequence: list[ClinicalEvent],
        h: TypeHierarchy,
    ) -> MatchList:
        """Find all non-overlapping matches anywhere in *sequence*."""
        results: MatchList = []
        idx = 0
        while idx < len(sequence):
            found = self.match(sequence, h, idx)
            if found:
                # Take the first (shortest) match and advance past it
                best = found[0]
                results.append(best)
                idx = sequence.index(best[-1]) + 1 if best else idx + 1
            else:
                idx += 1
        return results

    def has_match(
        self,
        sequence: list[ClinicalEvent],
        h: TypeHierarchy,
    ) -> bool:
        for i in range(len(sequence)):
            if self.match(sequence, h, i):
                return True
        return False


class AtomPattern(RTPPattern):
    """AION §11.2 (1): Single event atom."""

    def __init__(self, atom: RTPAtom) -> None:
        self.atom = atom

    def match(
        self,
        sequence: list[ClinicalEvent],
        h: TypeHierarchy,
        start_idx: int = 0,
    ) -> MatchList:
        results = []
        for i in range(start_idx, len(sequence)):
            e = sequence[i]
            if self.atom.matches_event(e, h):
                results.append([e])
        return results

    def __repr__(self) -> str:
        return repr(self.atom)


class ConcatPattern(RTPPattern):
    """
    AION §11.2 (2): π_1 →[r] π_2.
    Matches e_1 (from π_1) and e_2 (from π_2) where Allen(e_1, e_2, r).
    """

    def __init__(
        self,
        left:     RTPPattern,
        right:    RTPPattern,
        relation: AllenRelation = AllenRelation.PRECEDES,
    ) -> None:
        self.left     = left
        self.right    = right
        self.relation = relation

    def match(
        self,
        sequence: list[ClinicalEvent],
        h: TypeHierarchy,
        start_idx: int = 0,
    ) -> MatchList:
        results: MatchList = []
        left_matches = self.left.match(sequence, h, start_idx)
        for lm in left_matches:
            last_left = lm[-1]
            last_idx  = sequence.index(last_left)
            right_matches = self.right.match(sequence, h, last_idx + 1)
            for rm in right_matches:
                first_right = rm[0]
                if holds(self.relation, last_left.tau, first_right.tau):
                    results.append(lm + rm)
        return results

    def __repr__(self) -> str:
        return f"{self.left!r} →[{self.relation.value}] {self.right!r}"


class AlternatePattern(RTPPattern):
    """AION §11.2 (3): π_1 | π_2."""

    def __init__(self, left: RTPPattern, right: RTPPattern) -> None:
        self.left  = left
        self.right = right

    def match(
        self,
        sequence: list[ClinicalEvent],
        h: TypeHierarchy,
        start_idx: int = 0,
    ) -> MatchList:
        return (
            self.left.match(sequence, h, start_idx)
            + self.right.match(sequence, h, start_idx)
        )

    def __repr__(self) -> str:
        return f"({self.left!r} | {self.right!r})"


class KleeneStarPattern(RTPPattern):
    """
    AION §11.2 (4): π*.
    Matches zero or more non-overlapping occurrences of π.
    Returns one match per length (greedy).
    """

    def __init__(self, inner: RTPPattern) -> None:
        self.inner = inner

    def match(
        self,
        sequence: list[ClinicalEvent],
        h: TypeHierarchy,
        start_idx: int = 0,
    ) -> MatchList:
        # Zero occurrences: empty match at start
        results: MatchList = [[]]
        idx = start_idx

        while idx < len(sequence):
            inner_matches = self.inner.match(sequence, h, idx)
            if not inner_matches:
                break
            best = inner_matches[0]
            if not best:
                break
            results.append(results[-1] + best)
            idx = sequence.index(best[-1]) + 1

        return results

    def __repr__(self) -> str:
        return f"{self.inner!r}*"


class OptionPattern(RTPPattern):
    """AION §11.2 (5): π? = π | ε."""

    def __init__(self, inner: RTPPattern) -> None:
        self.inner = inner

    def match(
        self,
        sequence: list[ClinicalEvent],
        h: TypeHierarchy,
        start_idx: int = 0,
    ) -> MatchList:
        return [[]] + self.inner.match(sequence, h, start_idx)

    def __repr__(self) -> str:
        return f"{self.inner!r}?"


class RepetitionPattern(RTPPattern):
    """
    AION §11.2 (6): π{m,n} — m to n occurrences.
    """

    def __init__(self, inner: RTPPattern, min_rep: int, max_rep: int) -> None:
        if min_rep < 0 or max_rep < min_rep:
            raise ValueError(f"Invalid repetition bounds [{min_rep},{max_rep}]")
        self.inner   = inner
        self.min_rep = min_rep
        self.max_rep = max_rep

    def match(
        self,
        sequence: list[ClinicalEvent],
        h: TypeHierarchy,
        start_idx: int = 0,
    ) -> MatchList:
        results: MatchList = []
        current: Match = []
        idx = start_idx

        for rep in range(self.max_rep):
            inner_matches = self.inner.match(sequence, h, idx)
            if not inner_matches:
                break
            best = inner_matches[0]
            if not best:
                break
            current = current + best
            idx = sequence.index(best[-1]) + 1
            if rep + 1 >= self.min_rep:
                results.append(list(current))

        return results

    def __repr__(self) -> str:
        return f"{self.inner!r}{{{self.min_rep},{self.max_rep}}}"


# ── MatchOperator ─────────────────────────────────────────────────────────────

class MatchOperator:
    """
    AION §11.3: Match(π, p_k) = all matching subsequences of e_k.
    HasPattern(p, π) ⟺ Match(π, p) ≠ ∅.
    """

    def __init__(
        self,
        pattern:   RTPPattern,
        hierarchy: Optional[TypeHierarchy] = None,
    ) -> None:
        self.pattern   = pattern
        self._h        = hierarchy or default_hierarchy()

    def match(
        self,
        patient_id: str,
        event_set:  EventSet,
    ) -> MatchList:
        sequence = event_set.by_patient(patient_id)
        return self.pattern.match_all(sequence, self._h)

    def has_pattern(
        self,
        patient_id: str,
        event_set:  EventSet,
    ) -> bool:
        sequence = event_set.by_patient(patient_id)
        return self.pattern.has_match(sequence, self._h)

    def match_count(
        self,
        patient_id: str,
        event_set:  EventSet,
    ) -> int:
        return len(self.match(patient_id, event_set))


# ── Pattern Statistics (AION §11.5) ──────────────────────────────────────────

class PatternStats:
    """
    AION §11.5: freq, supp, conf over a cohort.
    """

    @staticmethod
    def frequency(
        operator:   MatchOperator,
        patient_ids: list[str],
        event_set:  EventSet,
    ) -> int:
        """freq(π, P_φ) = |{p ∈ P_φ | HasPattern(p, π)}|"""
        return sum(
            1 for pid in patient_ids
            if operator.has_pattern(pid, event_set)
        )

    @staticmethod
    def support(
        operator:    MatchOperator,
        patient_ids: list[str],
        event_set:   EventSet,
    ) -> float:
        """supp(π, P_φ) = freq / |P_φ|"""
        if not patient_ids:
            return 0.0
        return PatternStats.frequency(operator, patient_ids, event_set) / len(patient_ids)

    @staticmethod
    def confidence(
        operator1:   MatchOperator,
        operator2:   MatchOperator,
        patient_ids: list[str],
        event_set:   EventSet,
    ) -> float:
        """
        conf(π_1 ⇒ π_2, P_φ) = supp(π_1 ∧ π_2) / supp(π_1)
        """
        s1 = PatternStats.support(operator1, patient_ids, event_set)
        if s1 == 0.0:
            return 0.0

        both_pids = [
            pid for pid in patient_ids
            if operator1.has_pattern(pid, event_set)
            and operator2.has_pattern(pid, event_set)
        ]
        s12 = len(both_pids) / len(patient_ids)
        return s12 / s1


# ── Simplified TCFG (AION §11.4) ─────────────────────────────────────────────

@dataclass
class TCFGRule:
    """
    Production rule: A → X_1 →[r_1] X_2 →[r_2] ... →[r_{m-1}] X_m
    Non-terminals are str labels; terminals are RTPAtom.
    """
    lhs:      str                          # non-terminal A
    rhs:      list[str | RTPAtom]         # X_1, ..., X_m
    relations: list[AllenRelation]         # r_1, ..., r_{m-1}

    def __post_init__(self) -> None:
        if len(self.relations) != len(self.rhs) - 1:
            raise ValueError(
                f"TCFG rule needs {len(self.rhs)-1} relations "
                f"for {len(self.rhs)} RHS symbols"
            )


class TCFG:
    """
    AION §11.4: Temporal Context-Free Grammar G = (N, Σ_T, P_G, S).

    Simplified implementation: rules are expanded left-to-right.
    Each non-terminal is resolved to an AtomPattern or ConcatPattern.

    For AION's purposes (balanced pre/post measurement patterns),
    this is sufficient without full CYK complexity.
    """

    def __init__(
        self,
        start:     str,
        rules:     list[TCFGRule],
        hierarchy: Optional[TypeHierarchy] = None,
    ) -> None:
        self.start     = start
        self.rules     = rules
        self._h        = hierarchy or default_hierarchy()
        self._rule_map: dict[str, list[TCFGRule]] = {}
        for r in rules:
            self._rule_map.setdefault(r.lhs, []).append(r)

    def _expand(self, symbol: str | RTPAtom) -> RTPPattern:
        """Expand a symbol (terminal or non-terminal) into an RTPPattern."""
        if isinstance(symbol, RTPAtom):
            return AtomPattern(symbol)
        # Non-terminal: expand first matching rule
        rules = self._rule_map.get(symbol, [])
        if not rules:
            raise ValueError(f"No rule for non-terminal '{symbol}'")
        rule = rules[0]
        return self._expand_rule(rule)

    def _expand_rule(self, rule: TCFGRule) -> RTPPattern:
        """Build a ConcatPattern chain from a rule's RHS."""
        patterns = [self._expand(sym) for sym in rule.rhs]
        if len(patterns) == 1:
            return patterns[0]
        result = ConcatPattern(patterns[0], patterns[1], rule.relations[0])
        for i in range(2, len(patterns)):
            result = ConcatPattern(result, patterns[i], rule.relations[i - 1])
        return result

    def to_rtp(self) -> RTPPattern:
        """Compile the grammar into an equivalent RTPPattern."""
        return self._expand(self.start)

    def has_grammar_pattern(
        self,
        patient_id: str,
        event_set:  EventSet,
    ) -> bool:
        """HasGrammarPattern(p, G) — AION §11.3."""
        rtp = self.to_rtp()
        operator = MatchOperator(rtp, self._h)
        return operator.has_pattern(patient_id, event_set)


# ── Builder helpers ───────────────────────────────────────────────────────────

def atom(type_name: str, **attr_kw) -> AtomPattern:
    """Shorthand: atom("LabResult", value=lambda v: v > 4.0)"""
    pred = None
    if attr_kw:
        attr_name, attr_val = next(iter(attr_kw.items()))
        if callable(attr_val):
            pred = lambda e, a=attr_name, fn=attr_val: fn(e.attr(a))
        else:
            pred = lambda e, a=attr_name, v=attr_val: e.attr(a) == v
    return AtomPattern(RTPAtom(type_name, attr_pred=pred))


def seq(
    *patterns: RTPPattern,
    relation: AllenRelation = AllenRelation.PRECEDES,
) -> RTPPattern:
    """Chain patterns with *relation*: seq(a, b, c) → a →[r] b →[r] c"""
    if len(patterns) == 0:
        raise ValueError("seq() requires at least one pattern")
    if len(patterns) == 1:
        return patterns[0]
    result = ConcatPattern(patterns[0], patterns[1], relation)
    for p in patterns[2:]:
        result = ConcatPattern(result, p, relation)
    return result


def star(pattern: RTPPattern) -> KleeneStarPattern:
    return KleeneStarPattern(pattern)


def opt(pattern: RTPPattern) -> OptionPattern:
    return OptionPattern(pattern)


def rep(pattern: RTPPattern, min_n: int, max_n: int) -> RepetitionPattern:
    return RepetitionPattern(pattern, min_n, max_n)


def alt(*patterns: RTPPattern) -> RTPPattern:
    if len(patterns) < 2:
        raise ValueError("alt() requires at least two patterns")
    result = AlternatePattern(patterns[0], patterns[1])
    for p in patterns[2:]:
        result = AlternatePattern(result, p)
    return result
