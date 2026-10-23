"""Steam's subscribed files, rather than leftover Workshop download folders."""
import json
import re
from pathlib import Path


def keyvalues(text):
    lexer = re.compile(r'\s+|//[^\n]*|"(?:\\.|[^"\\])*"|[{}]|[^\s{}"]+')
    tokens, offset = [], 0
    while offset < len(text):
        match = lexer.match(text, offset)
        if not match:
            raise ValueError("Incomplete quoted KeyValues string")
        token = match.group()
        if not token.isspace() and not token.startswith("//"):
            tokens.append(token)
        offset = match.end()
    pos = 0

    def string(token):
        return re.sub(r'\\(["\\])', r'\1', token[1:-1]) if token.startswith('"') else token

    def block(nested=False, depth=0):
        nonlocal pos
        if depth > 32:
            raise ValueError("KeyValues nesting limit")
        result = {}
        while pos < len(tokens):
            token = tokens[pos]
            pos += 1
            if token == "}" and nested:
                return result
            if token in ("{", "}") or pos >= len(tokens):
                raise ValueError("Incomplete KeyValues")
            value = tokens[pos]
            pos += 1
            if value == "}":
                raise ValueError("Missing KeyValues value")
            result[string(token)] = block(True, depth + 1) if value == "{" else string(value)
        if nested:
            raise ValueError("Unclosed KeyValues block")
        return result

    return block()


def read(path):
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("Steam metadata too large")
    return keyvalues(path.read_text(encoding="utf-8-sig"))


def subscribed(roots, cache):
    """Return (IDs or None, metadata paths). An empty subscription list is valid.

    Keep the last complete list during Steam's temporary writes/replacements.
    Never change Steam's files or delete a downloaded wallpaper.
    """
    from catalog import atomic, load
    saved = load(cache / "subscriptions.json", {}) or {}
    watch, candidates, login_accounts, engine_accounts = set(), [], [], []
    for root in roots:
        userdata = root / "userdata"
        login = root / "config/loginusers.vdf"
        engine = root / "steamapps/common/wallpaper_engine/bin/workshopcache.json"
        for path in (root, userdata, login, login.parent, engine, engine.parent,
                     root / "steamapps/libraryfolders.vdf", root / "steamapps/workshop/appworkshop_431960.acf"):
            if path.exists():
                watch.add(str(path))
        try:
            users = read(login).get("users", {})
            login_accounts += [str(int(uid) & 0xffffffff) for uid, user in users.items()
                               if isinstance(user, dict) and (user.get("MostRecent") == "1" or user.get("AutoLogin") == "1") and uid.isdigit()]
        except (OSError, ValueError, AttributeError):
            pass
        try:
            user = json.loads(engine.read_text()).get("user")
            if user is not None:
                engine_accounts.append(str(int(user) & 0xffffffff))
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        if userdata.is_dir():
            for user in userdata.iterdir():
                if not user.is_dir() or not user.name.isdigit():
                    continue
                ugc = user / "ugc"
                path = ugc / "431960_subscriptions.vdf"
                watch.add(str(user))
                if ugc.is_dir():
                    watch.add(str(ugc))
                if path.is_file():
                    watch.add(str(path))
                    candidates.append(path)
    if not candidates:
        # A source may disappear briefly during an atomic replacement.
        path = Path(saved.get("source", "/nonexistent"))
        if any(path.is_relative_to(root) for root in roots) and "ids" in saved:
            return set(saved["ids"]), sorted(watch)
        return None, sorted(watch)  # Offline/local-only libraries still work.
    preferred = login_accounts + engine_accounts
    def rank(path):
        account = path.parent.parent.name
        return (preferred.index(account) if account in preferred else len(preferred), -path.stat().st_mtime_ns)
    source = sorted(candidates, key=rank)[0]
    try:
        data = read(source)["subscribedfiles"]
        if not isinstance(data, dict) or data.get("appid") != "431960":
            raise ValueError("Not a Wallpaper Engine subscription list")
        ids = set()
        for key, entry in data.items():
            if not key.isdigit():
                continue
            if not isinstance(entry, dict) or not str(entry.get("publishedfileid", "")).isdigit():
                raise ValueError("Incomplete subscribed file")
            if str(entry.get("disabled_locally", "0")) != "1":
                ids.add(str(entry["publishedfileid"]))
        atomic(cache / "subscriptions.json", {"source": str(source), "ids": sorted(ids)})
        return ids, sorted(watch)
    except (OSError, ValueError, KeyError):
        return (set(saved["ids"]) if saved.get("source") == str(source) and "ids" in saved else None), sorted(watch)
