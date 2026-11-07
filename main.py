"""Flow Launcher plugin: search and open Positron projects.

Project sources:
  1. Saved projects from the Project Manager extension (alefragnani.project-manager)
  2. Projects auto-detected by Project Manager (projects_cache_*.json)
  3. Folders/workspaces Positron has opened recently (User/workspaceStorage/*/workspace.json)

Talks to Flow Launcher over its JSON-RPC protocol directly (no external dependencies):
the request arrives as JSON in the last argv entry, the response is printed to stdout.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from urllib.parse import unquote, urlparse

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
ICON = os.path.join("Images", "positron.png")
ICON_FOLDER = os.path.join("Images", "folder.png")
ICON_COPY = os.path.join("Images", "copy.png")

APPDATA = os.environ.get("APPDATA", os.path.expanduser(r"~\AppData\Roaming"))
LOCALAPPDATA = os.environ.get("LOCALAPPDATA", os.path.expanduser(r"~\AppData\Local"))
POSITRON_USER_DIR = os.path.join(APPDATA, "Positron", "User")
PM_DIR = os.path.join(POSITRON_USER_DIR, "globalStorage", "alefragnani.project-manager")

DETECTED_CACHES = {
    "projects_cache_git.json": "Git",
    "projects_cache_vscode.json": "VS Code",
    "projects_cache_any.json": "Any",
    "projects_cache_mercurial.json": "Mercurial",
    "projects_cache_svn.json": "SVN",
}

# Environment variables Flow Launcher sets for its Python host that must not leak into
# Positron (they would otherwise reach the R/Python sessions Positron starts).
ENV_BLOCKLIST = {"PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTHONHOME", "ELECTRON_RUN_AS_NODE"}


# --------------------------------------------------------------------------- settings

def as_bool(value, default):
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "on")


def find_positron(configured):
    if configured and os.path.isfile(configured):
        return configured
    candidates = [
        os.path.join(LOCALAPPDATA, "Programs", "Positron", "Positron.exe"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Positron", "Positron.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Positron", "Positron.exe"),
    ]
    cli = shutil.which("positron")
    if cli:
        # <install>\bin\positron(.cmd) -> <install>\Positron.exe
        candidates.append(os.path.join(os.path.dirname(os.path.dirname(cli)), "Positron.exe"))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def read_jsonc(path):
    """Read a JSON-with-comments file (like settings.json)."""
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    # Strip // and /* */ comments that are outside of strings, then trailing commas.
    pattern = re.compile(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/', re.S)
    text = pattern.sub(lambda m: m.group(1) or "", text)
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    return json.loads(text)


def projects_dir(configured):
    if configured:
        return expand_path(configured)
    try:
        settings = read_jsonc(os.path.join(POSITRON_USER_DIR, "settings.json"))
        location = settings.get("projectManager.projectsLocation")
        if location:
            return expand_path(location)
    except (OSError, ValueError):
        pass
    return PM_DIR


# --------------------------------------------------------------------------- loading

def expand_path(path):
    path = path.replace("$home", os.path.expanduser("~"))
    return os.path.normpath(os.path.expandvars(os.path.expanduser(path)))


def uri_to_path(uri):
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None  # remote / virtual workspaces can't be opened by path
    path = unquote(parsed.path)
    if parsed.netloc:  # UNC: file://server/share/...
        return os.path.normpath(r"\\" + parsed.netloc + path)
    if re.match(r"^/[A-Za-z]:", path):
        path = path[1:]
    return os.path.normpath(path)


def key_of(path):
    return os.path.normcase(os.path.normpath(path))


def load_json_list(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def load_projects(settings):
    pm_dir = projects_dir(settings.get("projects_location"))
    hide_disabled = as_bool(settings.get("hide_disabled"), False)
    projects, seen = [], set()

    def add(name, path, kind, tags=(), profile=""):
        k = key_of(path)
        if k in seen:
            return
        seen.add(k)
        projects.append({"name": name, "path": path, "kind": kind,
                         "tags": list(tags or []), "profile": profile or ""})

    for p in load_json_list(os.path.join(pm_dir, "projects.json")):
        if not p.get("rootPath") or (hide_disabled and p.get("enabled") is False):
            continue
        path = expand_path(p["rootPath"])
        add(p.get("name") or os.path.basename(path), path, "saved", p.get("tags"), p.get("profile"))

    if as_bool(settings.get("include_detected"), True):
        for filename, label in DETECTED_CACHES.items():
            for p in load_json_list(os.path.join(pm_dir, filename)):
                if p.get("rootPath"):
                    path = expand_path(p["rootPath"])
                    add(p.get("name") or os.path.basename(path), path, "detected:" + label)

    if as_bool(settings.get("include_recent"), True):
        for path in recent_paths():
            name = os.path.basename(path)
            if name.lower().endswith(".code-workspace"):
                name = name[: -len(".code-workspace")] + " (workspace)"
            add(name, path, "recent")

    return projects


def recent_paths():
    """Folders/workspaces Positron has opened, most recent first."""
    root = os.path.join(POSITRON_USER_DIR, "workspaceStorage")
    entries = []
    try:
        dirs = os.listdir(root)
    except OSError:
        return []
    for d in dirs:
        meta = os.path.join(root, d, "workspace.json")
        try:
            with open(meta, encoding="utf-8") as f:
                data = json.load(f)
            mtime = os.path.getmtime(os.path.join(root, d))
        except (OSError, ValueError):
            continue
        uri = data.get("folder") or data.get("workspace")
        path = uri_to_path(uri) if uri else None
        if path and os.path.exists(path):
            entries.append((mtime, path))
    entries.sort(reverse=True)
    return [p for _, p in entries]


# --------------------------------------------------------------------------- matching

def fuzzy_score(query, text):
    """0 = no match. Substring/prefix/word-start matches beat scattered subsequences."""
    q, t = query.lower(), text.lower()
    if not q:
        return 1
    idx = t.find(q)
    if idx == 0:
        return 1000 - len(t)
    if idx > 0:
        word_start = not t[idx - 1].isalnum()
        return (800 if word_start else 600) - idx
    # subsequence match
    pos, gaps, last = 0, 0, -1
    for ch in q:
        found = t.find(ch, pos)
        if found < 0:
            return 0
        if last >= 0:
            gaps += found - last - 1
        last, pos = found, found + 1
    return max(1, 300 - gaps * 5)


def substring_score(query, text):
    idx = text.lower().find(query.lower())
    return 0 if idx < 0 else 500 - min(idx, 400)


def match(query, project):
    terms = query.split()
    if not terms:
        return 1
    total = 0
    tags = " ".join(project["tags"])
    for term in terms:
        # Fuzzy on name/tags; plain substring on the path (fuzzy over long paths is noise).
        s = max(fuzzy_score(term, project["name"]) * 2,
                fuzzy_score(term, tags),
                substring_score(term, project["path"]) // 2)
        if s <= 0:
            return 0
        total += s
    return total


# --------------------------------------------------------------------------- results

KIND_BONUS = {"saved": 300, "recent": 0}


def subtitle(project):
    parts = [project["path"]]
    if project["kind"] == "recent":
        parts.append("recent")
    elif project["kind"].startswith("detected:"):
        parts.append("detected (" + project["kind"].split(":", 1)[1] + ")")
    if project["tags"]:
        parts.append("tags: " + ", ".join(project["tags"]))
    if project["profile"]:
        parts.append("profile: " + project["profile"])
    if not os.path.exists(project["path"]):
        parts.append("NOT FOUND")
    return "  ·  ".join(parts)


def query(search, settings):
    projects = load_projects(settings)
    if not projects:
        return [message("No Positron projects found",
                        "Save projects with the Project Manager extension, or open folders in Positron")]

    scored = []
    for order, p in enumerate(projects):
        s = match(search.strip(), p)
        if s <= 0:
            continue
        # Empty query: keep source order (saved -> detected -> recent by recency).
        score = (len(projects) - order) if not search.strip() else s + KIND_BONUS.get(p["kind"], 100)
        scored.append((score, p))

    if not scored:
        return [message("No matching Positron project", search)]

    return [{
        "Title": p["name"],
        "SubTitle": subtitle(p),
        "IcoPath": ICON,
        "Score": score,
        "JsonRPCAction": {"method": "open_project",
                          "parameters": [p["path"], p["profile"], False, settings.get("positron_path", "")]},
        "ContextData": [p["path"], p["profile"], settings.get("positron_path", "")],
    } for score, p in scored]


def context_menu(data):
    path, profile, positron_path = (list(data) + ["", "", ""])[:3]
    return [
        {
            "Title": "Open in new Positron window",
            "SubTitle": path,
            "IcoPath": ICON,
            "JsonRPCAction": {"method": "open_project", "parameters": [path, profile, True, positron_path]},
        },
        {
            "Title": "Open in Explorer",
            "SubTitle": path,
            "IcoPath": ICON_FOLDER,
            "JsonRPCAction": {"method": "open_explorer", "parameters": [path]},
        },
        {
            "Title": "Copy path",
            "SubTitle": path,
            "IcoPath": ICON_COPY,
            # Calls Flow's IPublicAPI.CopyToClipboard(string text, bool directCopy, bool showNotification)
            "JsonRPCAction": {"method": "Flow.Launcher.CopyToClipboard", "parameters": [path, True, True]},
        },
    ]


def message(title, sub=""):
    return {"Title": title, "SubTitle": sub, "IcoPath": ICON}


# --------------------------------------------------------------------------- actions

def clean_env():
    return {k: v for k, v in os.environ.items()
            if k.upper() not in ENV_BLOCKLIST and not k.upper().startswith("FLOW_")}


def detach(args):
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(args, env=clean_env(), creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_project(path, profile="", new_window=False, positron_path=""):
    exe = find_positron(positron_path)
    if not exe:
        return show_msg("Positron not found", "Set the Positron executable path in the plugin settings")
    args = [exe]
    if new_window:
        args.append("--new-window")
    if profile:
        args += ["--profile", profile]
    args.append(path)
    detach(args)


def open_explorer(path):
    if os.path.isfile(path):  # .code-workspace file -> select it
        detach(["explorer.exe", "/select,", path])
    else:
        detach(["explorer.exe", path])


def show_msg(title, sub):
    # Ask Flow to show a notification: return a JSON-RPC request back to Flow.
    print(json.dumps({"method": "Flow.Launcher.ShowMsg", "parameters": [title, sub, ""]}))


# --------------------------------------------------------------------------- entry

def main():
    if len(sys.argv) < 2:
        return
    request = json.loads(sys.argv[-1])
    method = request.get("method")
    params = request.get("parameters") or []
    settings = request.get("settings") or {}

    if method == "query":
        result = query(params[0] if params else "", settings)
    elif method == "context_menu":
        result = context_menu(params[0] if params else [])
    elif method == "open_project":
        open_project(*params)
        return
    elif method == "open_explorer":
        open_explorer(*params)
        return
    else:
        return
    sys.stdout.buffer.write(json.dumps({"result": result}).encode("utf-8"))


if __name__ == "__main__":
    main()
