from dataclasses import dataclass

JSON_REPO = 'https://pypi.org/pypi'
SIMPLE_REPO = "https://pypi.org/simple"


@dataclass
class Options:
    json_only: bool = False
    json_repo: str = JSON_REPO
    simple_only: bool = False
    simple_repo: str = SIMPLE_REPO
    info: bool = False
    verbose: bool = False
    unpinned: bool = False
    auto_update: bool = False
