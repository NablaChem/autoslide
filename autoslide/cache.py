"""Append-only cache of rendered LaTeX, keyed by block content *and* layout.

The key mixes in a fingerprint of the templates and theme, so editing a
template invalidates the cache instead of silently serving the old layout.
"""

import os
import json
import hashlib
from dataclasses import asdict, is_dataclass
from typing import Dict, List, Optional

from .models import Block

CACHE_FILENAME = ".autoslide.cache"

#: Bumped when the entry format changes; older entries are ignored.
FORMAT_VERSION = 2


class OutputCache:
    def __init__(
        self,
        output_dir: str = ".",
        fingerprint: str = "",
        read_enabled: bool = True,
        write_enabled: bool = True,
    ):
        self.path = os.path.join(output_dir, CACHE_FILENAME)
        self.fingerprint = fingerprint
        self.read_enabled = read_enabled
        self.write_enabled = write_enabled
        self._entries: Optional[Dict[str, str]] = None

    # -- keys ---------------------------------------------------------

    def key(self, blocks: List[Block], **extra) -> str:
        """Deterministic hash of the blocks, the extra context and the templates."""
        payload = {
            "version": FORMAT_VERSION,
            "fingerprint": self.fingerprint,
            "extra": _plain(extra),
            "blocks": [
                {
                    "type": block.type.value,
                    "content": block.content,
                    "metadata": _plain(block.metadata or {}),
                }
                for block in blocks
            ],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    # -- access -------------------------------------------------------

    def get(self, key: str) -> Optional[str]:
        if not self.read_enabled:
            return None
        return self._load().get(key)

    def put(self, key: str, latex: str) -> None:
        entries = self._load()
        entries[key] = latex
        if not self.write_enabled:
            return
        try:
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps({"hash": key, "latex_source": latex}) + "\n")
        except OSError:
            pass  # caching is best effort

    def _load(self) -> Dict[str, str]:
        if self._entries is not None:
            return self._entries
        self._entries = {}
        if not self.read_enabled or not os.path.exists(self.path):
            return self._entries
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if line:
                        entry = json.loads(line)
                        self._entries[entry["hash"]] = entry["latex_source"]
        except (json.JSONDecodeError, KeyError, OSError):
            self._entries = {}  # corrupted - start fresh
        return self._entries


def _plain(value):
    """Make nested metadata JSON-serialisable and order-independent."""
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, dict):
        return {key: _plain(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value
