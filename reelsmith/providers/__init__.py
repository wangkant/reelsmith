"""Asset tools (contract section 9). Each takes the project path first, writes into assets/ or voice/, registers
what it made in project.json and returns (text, is_error); none raises, none echoes a key."""
from .animate import animate
from .capture import capture
from .config import Context, ProviderError, context, redact
from .draw import draw
from .footage import frames, probe, scenes, silences
from .importer import assets, import_asset
from .ledger import BudgetRefused, Ledger, spent_usd
from .transcribe import transcribe
from .tts import speak

__all__ = ["speak", "capture", "draw", "animate", "import_asset", "assets", "probe", "frames", "scenes", "silences",
           "transcribe", "Ledger", "BudgetRefused", "ProviderError", "Context", "context", "redact", "spent_usd"]
