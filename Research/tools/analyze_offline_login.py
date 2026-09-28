"""Summarize the fixed-build frontend Blueprint's login control flow."""
import json
import sys
from pathlib import Path

exports = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
graph = next(item for item in exports if item.get("Name") == "ExecuteUbergraph_FrontendMainMenu_BP")
terms = ("AttemptLogin", "IsOfflineMode", "ShowLoginFailure", "GotoState",
         "LoginStatus", "OnUserLoggedIn", "Play Offline", "FrontendLogin")
for item in graph["ScriptBytecode"]:
    index = item.get("StatementIndex", 0)
    if (0 <= index <= 2000 or 5800 <= index <= 7500) and (index < 2000 or any(term in json.dumps(item, ensure_ascii=False) for term in terms)):
        value = json.dumps(item, ensure_ascii=False)
        print(index, item.get("Inst"), item.get("Function"),
              [term for term in terms if term in value], item.get("CodeOffset"))
