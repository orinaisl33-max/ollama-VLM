"""Incremental sentence buffering. No model text is executed or interpreted as HTML."""

import re

from .speech import prepare_speech


class SentenceBuffer:
    def __init__(self):
        self.pending = ""
        self.fence = None
        self.table = False

    def feed(self, text, final=False):
        self.pending += text
        ready = []
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", 1)
            ready.extend(self._line(line))
        if final:
            ready.extend(self._line(self.pending))
            self.pending = ""
        elif (
            not self.fence
            and "|" not in self.pending
            and not self.pending.lstrip().startswith(("`", "~"))
        ):
            # Hold ambiguous trailing punctuation (English dots may be decimals/URLs).
            while True:
                boundary = next(
                    (
                        match.end()
                        for match in re.finditer(r"[。！？!?]|\.(?=\s)", self.pending)
                        if match.end() >= 16 and self._balanced(self.pending[: match.end()])
                    ),
                    None,
                )
                if boundary is None:
                    break
                ready.extend(self._prose(self.pending[:boundary]))
                self.pending = self.pending[boundary:]
            # Long sentences: split at a natural comma/space, never in a token.
            if len(self.pending) > 180:
                cuts = list(re.finditer(r"[，；、;]|\s", self.pending[:180]))
                if cuts and cuts[-1].end() >= 60:
                    end = cuts[-1].end()
                    if self._balanced(self.pending[:end]):
                        ready.extend(self._prose(self.pending[:end]))
                        self.pending = self.pending[end:]
        return ready

    @staticmethod
    def _balanced(text):
        return (
            text.count("`") % 2 == 0
            and text.count("[") == text.count("]")
            and text.count("(") == text.count(")")
        )

    def _line(self, line):
        fence = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if fence:
            marker = fence[1]
            if self.fence is None:
                self.fence = marker
                return ["程式碼區塊已略過。"]
            if marker[0] == self.fence[0] and len(marker) >= len(self.fence):
                self.fence = None
            return []
        if self.fence:
            return []
        if "|" in line:
            if self.table:
                return []
            self.table = True
            return ["表格內容請參閱畫面。"]
        self.table = False
        return self._prose(line)

    @staticmethod
    def _prose(text):
        cleaned = prepare_speech(text).text.strip()
        return [cleaned] if cleaned else []
