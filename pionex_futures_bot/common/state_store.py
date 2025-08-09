from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


class StateStore:
    """JSON-backed lightweight state store for open positions per symbol.

    This persists minimal fields required to resume after a restart.
    """

    def __init__(self, path: str | Path = "runtime_state.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> Dict[str, Dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data  # type: ignore[return-value]
        except Exception:
            pass
        return {}

    def save(self, state: Dict[str, Dict[str, Any]]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")
        tmp.replace(self.path)

    def update_symbol(self, symbol: str, fields: Dict[str, Any]) -> None:
        data = self.load()
        sym = data.get(symbol, {})
        sym.update(fields)
        data[symbol] = sym
        self.save(data)

    def clear_symbol(self, symbol: str) -> None:
        data = self.load()
        if symbol in data:
            del data[symbol]
            self.save(data)


