"""LegalSearchProvider — stub per M1 (§96/137).

In M2: implementazione con web search generica + opzione "incolla manualmente
i risultati". La query esce sempre pseudonimizzata.
"""
from __future__ import annotations

from ai.interfaces import SuggerimentoRicerca


class StubLegalSearchProvider:
    def search(self, query: str) -> list[SuggerimentoRicerca]:
        return []
