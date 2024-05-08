#!/usr/bin/env python

import os.path
from dataclasses import dataclass
from enum import Enum

from requirements.requirement import Requirement


class LineType(Enum):
    requirement = "requirement"
    error = "error"
    unsupported = "unsupported"
    other = "other"


class UpdateStatus(Enum):
    ok = 'ok'
    behind = 'behind'
    unpinned = 'unpinned'
    unknown = 'unknown'


@dataclass
class Line:
    ltype: LineType

    filename: str
    lineno: int
    pkgname: str | None = None
    line: str | None = None
    error: str | None = None
    spec: str | None = None

    latest: str | None = None
    url: str | None = None

    status: UpdateStatus = UpdateStatus.unknown

    @property
    def location(self) -> str:
        return f"{self.filename}:{self.lineno}"


class ReqFile:
    def __init__(self, filepath: str) -> None:
        self.filepath: str = filepath
        self.filename: str = os.path.basename(filepath)
        self.lines: list[Line] = []
        self.other_files: list[str] = []
        self._lineno = 1

        with open(self.filepath, "r") as fh:
            lines = fh.readlines()

        for line in lines:
            self._parse_line(line)
            self._lineno += 1

    def store(
        self,
        line: str,
        status: LineType,
        pkgname: str | None = None,
        error: str | None = None,
        spec: str | None = None,
    ) -> None:
        self.lines.append(Line(status, self.filename, self._lineno, pkgname, line, error, spec))

    def _parse_line(self, line: str) -> None:
        if line.strip() == "":
            return self.store(line, LineType.other)

        elif not line or line.startswith("#"):
            return self.store(line, LineType.other)

        # Other requirements files.
        elif line.startswith("-r") or line.startswith("--requirement"):
            _, new_filename = line.split()
            new_file = os.path.join(os.path.dirname(self.filepath or "."), new_filename)
            if not os.path.exists(new_file):
                return self.store(
                    line,
                    LineType.error,
                    error="Requirement file does not exist",
                    pkgname=new_file,
                )
            else:
                self.other_files.append(new_file)
                return self.store(line, LineType.other)

        elif line.startswith("-"):
            return self.store(line, LineType.unsupported, error="Unsupported argument")

        elif line.startswith("./"):
            return self.store(line, LineType.unsupported, error="Local files unsupported")

        else:
            try:
                req = Requirement.parse(line)
            except Exception as ex:
                return self.store(
                    line,
                    LineType.error,
                    error=f"Could not parse line: {ex}",
                )

            if req.uri:
                return self.store(
                    line,
                    LineType.unsupported,
                    pkgname=req.name,
                    error="Package URLs unsupported",
                )

            if len(req.specs) == 0:
                # Unpinned requirement.
                return self.store(line, LineType.requirement, pkgname=req.name)

            if len(req.specs) != 1:
                return self.store(
                    line,
                    LineType.unsupported,
                    error="Unsupported version spec",
                    pkgname=req.name,
                )

            if req.specs[0][0] not in ["==", ">="]:
                return self.store(
                    line,
                    LineType.unsupported,
                    error="Unsupported version spec",
                    pkgname=req.name,
                )

            self.store(line, LineType.requirement, pkgname=req.name, spec=req.specs[0][1])
