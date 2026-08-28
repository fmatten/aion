# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""TCFG — Temporale kontextfreie Grammatik für klinische Verläufe.

Mathematisches Modell:
    G = (N, Σ, P, S) mit:
        N: Nichtterminale (z. B. Krankheitsphasen)
        Σ: Terminale (Ereignistypen)
        P: Produktionen A → α
        S: Startsymbol

    Die Grammatik liegt in Chomsky-Normalform vor:
        A → BC  oder  A → a

Algorithmen:
    - cyk_parse:        exakter CYK-Parser, O(n³ · |G|)
    - beam_search_parse: approximativer Beam-Parser, O(n² · k)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TCFGResult:
    matches: bool
    probability: float = 0.0
    parse_tree: Optional[dict] = None


class TCFG:
    """Temporale CFG in Chomsky-Normalform."""

    def __init__(
        self,
        grammar: dict[str, list[list[str]]],
        start_symbol: str = "S",
        production_probs: Optional[dict[tuple, float]] = None,
    ) -> None:
        """
        Args:
            grammar:           {Nichtterminal: [[Produktion1], [Produktion2], ...]}
                               Produktionen müssen Länge 1 (Terminal) oder 2 (zwei NT) haben.
            start_symbol:      Startsymbol S
            production_probs:  optional: P(A → α), Defaults zu uniformer Verteilung
        """
        self.grammar = grammar
        self.start = start_symbol
        self.terminals = self._extract_terminals()
        self.nonterminals = set(grammar.keys())
        self.production_probs = production_probs or self._uniform_probs()
        self._validate_cnf()

    def _extract_terminals(self) -> set[str]:
        terms: set[str] = set()
        for prods in self.grammar.values():
            for prod in prods:
                for sym in prod:
                    if sym not in self.grammar:
                        terms.add(sym)
        return terms

    def _uniform_probs(self) -> dict[tuple, float]:
        probs: dict[tuple, float] = {}
        for nt, prods in self.grammar.items():
            n = len(prods)
            for prod in prods:
                probs[(nt, tuple(prod))] = 1.0 / n
        return probs

    def _validate_cnf(self) -> None:
        for nt, prods in self.grammar.items():
            for prod in prods:
                if len(prod) == 1:
                    if prod[0] in self.grammar:
                        raise ValueError(
                            f"Produktion {nt} → {prod[0]} muss Terminal sein (CNF)."
                        )
                elif len(prod) == 2:
                    if any(s not in self.grammar for s in prod):
                        raise ValueError(
                            f"Produktion {nt} → {prod} muss zwei Nichtterminale haben (CNF)."
                        )
                else:
                    raise ValueError(
                        f"Produktion {nt} → {prod} ist nicht in Chomsky-Normalform."
                    )

    # ── CYK-Algorithmus ───────────────────────────────────────────
    def cyk_parse(self, sequence: list[str]) -> TCFGResult:
        """Exakter CYK-Parser. Liefert Wahrheitswert + Parse-Baum.

        Komplexität: O(n³ · |G|).
        """
        n = len(sequence)
        if n == 0:
            return TCFGResult(matches=False)

        # table[i][j] = {NT: (back_pointer)}, Bereich sequence[i:j+1]
        table: list[list[dict]] = [
            [dict() for _ in range(n)] for _ in range(n)
        ]

        # Diagonale (Terminale)
        for i, term in enumerate(sequence):
            for nt, prods in self.grammar.items():
                for prod in prods:
                    if len(prod) == 1 and prod[0] == term:
                        prob = self.production_probs.get((nt, tuple(prod)), 1.0)
                        table[i][i][nt] = ("term", term, prob)

        # Diagonalen aufbauen
        # Konvention: Wahrscheinlichkeit ist immer das LETZTE Element des Backpointers.
        # term-Eintrag: ("term", terminal, prob)        — len 3
        # rule-Eintrag: ("rule", (A, B, k), prob)       — len 3
        for length in range(2, n + 1):
            for i in range(n - length + 1):
                j = i + length - 1
                for k in range(i, j):
                    for nt, prods in self.grammar.items():
                        for prod in prods:
                            if len(prod) == 2:
                                A, B = prod
                                if A in table[i][k] and B in table[k + 1][j]:
                                    pA = table[i][k][A][-1]
                                    pB = table[k + 1][j][B][-1]
                                    p_rule = self.production_probs.get((nt, tuple(prod)), 1.0)
                                    p = pA * pB * p_rule
                                    # Best-Score-Variante (Viterbi)
                                    if nt not in table[i][j] or table[i][j][nt][-1] < p:
                                        table[i][j][nt] = ("rule", (A, B, k), p)

        if self.start in table[0][n - 1]:
            entry = table[0][n - 1][self.start]
            prob = entry[-1]
            tree = self._build_tree(table, sequence, 0, n - 1, self.start)
            return TCFGResult(matches=True, probability=prob, parse_tree=tree)
        return TCFGResult(matches=False, probability=0.0)

    def _build_tree(self, table, sequence, i, j, nt) -> dict:
        entry = table[i][j].get(nt)
        if entry is None:
            return {"label": nt, "error": "no parse"}
        kind = entry[0]
        if kind == "term":
            return {"label": nt, "terminal": entry[1]}
        if kind == "rule":
            A, B, k = entry[1]
            return {
                "label": nt,
                "children": [
                    self._build_tree(table, sequence, i, k, A),
                    self._build_tree(table, sequence, k + 1, j, B),
                ],
            }
        return {"label": nt}

    # ── Beam Search ───────────────────────────────────────────────
    def beam_search_parse(self, sequence: list[str], beam_width: int = 100) -> TCFGResult:
        """Approximative Bottom-Up-Suche mit Beam.

        Komplexität: O(n² · k). Geeignet für lange Sequenzen.
        """
        n = len(sequence)
        if n == 0:
            return TCFGResult(matches=False)

        # Beam[i][j] = Liste von (NT, prob) absteigend sortiert
        beam: list[list[list[tuple[str, float]]]] = [
            [[] for _ in range(n)] for _ in range(n)
        ]

        for i, term in enumerate(sequence):
            cands: list[tuple[str, float]] = []
            for nt, prods in self.grammar.items():
                for prod in prods:
                    if len(prod) == 1 and prod[0] == term:
                        p = self.production_probs.get((nt, tuple(prod)), 1.0)
                        cands.append((nt, p))
            cands.sort(key=lambda x: -x[1])
            beam[i][i] = cands[:beam_width]

        for length in range(2, n + 1):
            for i in range(n - length + 1):
                j = i + length - 1
                cands: list[tuple[str, float]] = []
                for k in range(i, j):
                    left = dict(beam[i][k])
                    right = dict(beam[k + 1][j])
                    for nt, prods in self.grammar.items():
                        for prod in prods:
                            if len(prod) == 2:
                                A, B = prod
                                if A in left and B in right:
                                    p_rule = self.production_probs.get((nt, tuple(prod)), 1.0)
                                    cands.append((nt, left[A] * right[B] * p_rule))
                # Aggregiere pro NT mit Max
                best: dict[str, float] = {}
                for nt, p in cands:
                    if p > best.get(nt, 0):
                        best[nt] = p
                ranked = sorted(best.items(), key=lambda x: -x[1])
                beam[i][j] = ranked[:beam_width]

        for nt, p in beam[0][n - 1]:
            if nt == self.start:
                return TCFGResult(matches=True, probability=p)
        return TCFGResult(matches=False, probability=0.0)


    # ── Pattern-Mining ────────────────────────────────────────────
    @staticmethod
    def mine_patterns(
        sequences: list[list[str]],
        min_length: int = 2,
        max_length: int = 5,
        min_support: float = 0.3,
    ) -> dict[tuple[str, ...], float]:
        """Findet häufige zusammenhängende Teilsequenzen über mehrere Sequenzen.

        Konzept:
            Ein Pattern p = (s_1, ..., s_k) hat Support
                support(p) = |{seq ∈ sequences | p ist Teilstring von seq}| / |sequences|
            Liefert alle Patterns mit Länge ∈ [min_length, max_length]
            und support ≥ min_support.

        Algorithmus: Apriori-artig — für Länge L+1 werden nur Patterns
        kandidiert, deren beide L-Suffixe/Präfixe frequent sind. Das hält
        die Kandidatenzahl klein. O(N · ∑_L L · max_seq_len).

        Args:
            sequences:    Liste von Token-Sequenzen (z. B. Ereignistypen pro
                          Patientenaufenthalt, chronologisch sortiert)
            min_length:   minimale Pattern-Länge (≥ 2 sinnvoll, ≥ 1 erlaubt)
            max_length:   maximale Pattern-Länge
            min_support:  Schwelle in [0, 1]

        Returns:
            {pattern_tuple: support_fraction}, absteigend nach Support sortiert.
        """
        if not sequences:
            return {}
        if min_length < 1 or max_length < min_length:
            raise ValueError(f"Ungültiger Längenbereich: [{min_length}, {max_length}]")
        if not (0.0 <= min_support <= 1.0):
            raise ValueError(f"min_support muss in [0,1] liegen: {min_support}")

        n_seq = len(sequences)
        threshold = min_support * n_seq

        # ── Schritt 1: Frequente 1-Patterns (Tokens) ──
        token_support: dict[tuple[str, ...], int] = {}
        for seq in sequences:
            for token in set(seq):  # einmal pro Sequenz zählen
                token_support[(token,)] = token_support.get((token,), 0) + 1
        frequent: dict[tuple[str, ...], int] = {
            p: c for p, c in token_support.items() if c >= threshold
        }

        # ── Schritt 2..max_length: Pattern-Erweiterung ──
        all_frequent: dict[tuple[str, ...], int] = dict(frequent)
        current_level = frequent

        for L in range(2, max_length + 1):
            if not current_level:
                break
            # Kandidatenmenge: alle Tokens, die als 1-Pattern frequent sind
            frequent_tokens = {p[0] for p in frequent.keys()}

            # Generiere Kandidaten der Länge L aus Length-(L-1)-Patterns
            # × frequente Tokens. Apriori-Pruning: alle (L-1)-Suffixe der Kandidaten
            # müssen ebenfalls frequent sein.
            candidates: set[tuple[str, ...]] = set()
            for prefix in current_level:
                for token in frequent_tokens:
                    cand = prefix + (token,)
                    # Pruning: alle Längen-L-Subpatterns müssen frequent sein
                    # Hier reicht der Suffix der Länge L-1 (Apriori-Eigenschaft)
                    suffix = cand[1:]
                    if suffix in current_level or len(suffix) < 2:
                        candidates.add(cand)

            if not candidates:
                break

            # Zähle Support der Kandidaten
            counts: dict[tuple[str, ...], int] = {c: 0 for c in candidates}
            for seq in sequences:
                # Kandidaten, die in dieser Sequenz vorkommen
                hits: set[tuple[str, ...]] = set()
                for i in range(len(seq) - L + 1):
                    window = tuple(seq[i:i + L])
                    if window in counts:
                        hits.add(window)
                for h in hits:
                    counts[h] += 1

            # Filter
            new_frequent = {p: c for p, c in counts.items() if c >= threshold}
            all_frequent.update(new_frequent)
            current_level = new_frequent

        # Filter nach min_length, normieren auf Support-Fraktion, sortieren
        result = {
            p: c / n_seq
            for p, c in all_frequent.items()
            if len(p) >= min_length
        }
        return dict(sorted(result.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0])))

    def extend_with_patterns(
        self,
        patterns: dict[tuple[str, ...], float],
        *,
        prefix: str = "P_",
    ) -> "TCFG":
        """Erzeugt eine neue Grammatik, in der frequente Patterns als
        eigene Nichtterminale eingeführt werden.

        Patterns der Länge > 2 werden in CNF binarisiert (rechtsassoziativ):
            (a, b, c)  →  N_abc → a N_bc, N_bc → b c

        Existierende Produktionen werden durch die neuen Nichtterminale
        ersetzt, wo das Pattern zusammenhängend in einer Right-Hand-Side
        auftritt.

        Args:
            patterns: Wie von mine_patterns(...) zurückgegeben
            prefix:   Präfix der neu erzeugten Nichtterminale

        Returns:
            Neues TCFG-Objekt (Original bleibt unverändert).
        """
        new_grammar: dict[str, list[list[str]]] = {
            nt: [list(prod) for prod in prods]
            for nt, prods in self.grammar.items()
        }
        new_probs = dict(self.production_probs)

        # Sortiere Patterns von längsten zu kürzesten, damit verschachtelte
        # Patterns korrekt aufgelöst werden
        sorted_patterns = sorted(patterns.keys(), key=len, reverse=True)
        pattern_to_nt: dict[tuple[str, ...], str] = {}

        for pat in sorted_patterns:
            if len(pat) < 2:
                continue
            nt_name = prefix + "_".join(pat)
            # Falls Konflikt mit bestehenden Namen, anhängen
            base = nt_name
            i = 1
            while nt_name in new_grammar:
                nt_name = f"{base}_{i}"
                i += 1
            pattern_to_nt[pat] = nt_name

            # Binarisierung in CNF: (a, b, c, d) → nt → a R, R → b S, S → c d
            self._binarize_pattern(nt_name, list(pat), new_grammar, new_probs, prefix)

        # Ersetze Patterns in bestehenden Produktionen
        for nt, prods in list(new_grammar.items()):
            new_prods: list[list[str]] = []
            for prod in prods:
                replaced = self._replace_patterns_in_production(prod, pattern_to_nt)
                new_prods.append(replaced)
            new_grammar[nt] = new_prods

        return TCFG(
            grammar=new_grammar,
            start_symbol=self.start,
            production_probs=new_probs,
        )

    @staticmethod
    def _binarize_pattern(
        nt_name: str,
        pat: list[str],
        grammar: dict[str, list[list[str]]],
        probs: dict[tuple, float],
        prefix: str,
    ) -> None:
        """Erzeugt CNF-Produktionen für ein Pattern beliebiger Länge ≥ 2."""
        if len(pat) == 2:
            grammar[nt_name] = [pat[:]]
            probs[(nt_name, tuple(pat))] = 1.0
            return
        # Rechtsassoziativ: nt → pat[0] tail_nt, tail_nt → pat[1] ... pat[-1]
        tail_name = f"{prefix}TAIL_{nt_name}"
        i = 1
        while tail_name in grammar:
            tail_name = f"{prefix}TAIL_{nt_name}_{i}"
            i += 1
        grammar[nt_name] = [[pat[0], tail_name]]
        probs[(nt_name, (pat[0], tail_name))] = 1.0
        # Rekursiv den Rest
        TCFG._binarize_pattern(tail_name, pat[1:], grammar, probs, prefix)

    @staticmethod
    def _replace_patterns_in_production(
        prod: list[str],
        pattern_to_nt: dict[tuple[str, ...], str],
    ) -> list[str]:
        """Ersetzt zusammenhängende Patterns durch die zugehörigen Nichtterminale.

        Greedy-Replacement von links nach rechts, längstes Match zuerst.
        """
        if not pattern_to_nt:
            return list(prod)
        result: list[str] = []
        i = 0
        # Patterns nach Länge absteigend, damit längstes Match zuerst
        sorted_pats = sorted(pattern_to_nt.keys(), key=len, reverse=True)
        while i < len(prod):
            matched = False
            for pat in sorted_pats:
                L = len(pat)
                if i + L <= len(prod) and tuple(prod[i:i + L]) == pat:
                    result.append(pattern_to_nt[pat])
                    i += L
                    matched = True
                    break
            if not matched:
                result.append(prod[i])
                i += 1
        return result
