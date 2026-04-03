#!/usr/bin/env python3
"""
📊 Claude Code Session Analyzer
Analyze your Claude Code usage: sessions, tokens, tools, costs.
"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter, defaultdict

# ANSI colors
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"
GRAY = "\033[90m"

CLAUDE_DIR = Path.home() / ".claude"
HISTORY_FILE = CLAUDE_DIR / "history.jsonl"


def colored(text, color):
    return f"{color}{text}{RESET}"


def bar_chart(value, max_val, width=30, color=GREEN):
    if max_val == 0:
        return f"{color}{'░' * width}{RESET}"
    filled = int(width * value / max_val)
    return f"{color}{'█' * filled}{GRAY}{'░' * (width - filled)}{RESET}"


def format_tokens(n):
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def format_cost(tokens_in, tokens_out):
    """Estimate cost based on Claude pricing."""
    # Approximate Sonnet pricing: $3/M input, $15/M output
    cost_in = tokens_in / 1_000_000 * 3
    cost_out = tokens_out / 1_000_000 * 15
    return cost_in + cost_out


def load_history():
    """Load session history from JSONL file."""
    sessions = []
    if not HISTORY_FILE.exists():
        return sessions
    with open(HISTORY_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                sessions.append(entry)
            except json.JSONDecodeError:
                continue
    return sessions


def analyze_sessions(sessions):
    """Analyze session data."""
    stats = {
        "total_sessions": len(sessions),
        "total_messages": 0,
        "total_tokens_in": 0,
        "total_tokens_out": 0,
        "tools_used": Counter(),
        "models_used": Counter(),
        "sessions_by_day": defaultdict(int),
        "sessions_by_hour": defaultdict(int),
        "projects": Counter(),
        "durations": [],
        "first_session": None,
        "last_session": None,
    }

    for s in sessions:
        # Extract timestamp
        ts = s.get("timestamp") or s.get("created_at") or s.get("ts")
        if ts:
            try:
                if isinstance(ts, (int, float)):
                    dt = datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts)
                else:
                    dt = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))

                day = dt.strftime("%Y-%m-%d")
                hour = dt.hour
                stats["sessions_by_day"][day] += 1
                stats["sessions_by_hour"][hour] += 1

                if stats["first_session"] is None or dt < stats["first_session"]:
                    stats["first_session"] = dt
                if stats["last_session"] is None or dt > stats["last_session"]:
                    stats["last_session"] = dt
            except (ValueError, OSError):
                pass

        # Tools
        tool = s.get("tool") or s.get("type")
        if tool:
            stats["tools_used"][tool] += 1

        # Tokens
        usage = s.get("usage") or {}
        stats["total_tokens_in"] += usage.get("input_tokens", 0) or usage.get("tokens_in", 0) or 0
        stats["total_tokens_out"] += usage.get("output_tokens", 0) or usage.get("tokens_out", 0) or 0

        # Model
        model = s.get("model") or s.get("model_id")
        if model:
            stats["models_used"][model] += 1

        # Project
        project = s.get("project") or s.get("cwd") or s.get("directory")
        if project:
            # Simplify path
            project = str(project).replace(str(Path.home()), "~")
            stats["projects"][project] += 1

        stats["total_messages"] += 1

    return stats


def scan_projects():
    """Scan Claude Code project directories for additional data."""
    projects_dir = CLAUDE_DIR / "projects"
    project_info = []

    if not projects_dir.exists():
        return project_info

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        info = {"name": project_dir.name, "files": []}

        # Check for CLAUDE.md, memory, etc.
        for f in project_dir.rglob("*"):
            if f.is_file():
                info["files"].append(str(f.relative_to(project_dir)))

        project_info.append(info)

    return project_info


def scan_plugins():
    """Find installed plugins/skills."""
    plugins = []
    plugins_dir = CLAUDE_DIR / "plugins"
    if plugins_dir.exists():
        for p in plugins_dir.iterdir():
            if p.is_dir():
                plugins.append(p.name)
    return plugins


def scan_settings():
    """Read settings.json."""
    settings_file = CLAUDE_DIR / "settings.json"
    if settings_file.exists():
        with open(settings_file) as f:
            return json.load(f)
    return {}


def print_report(stats, projects, plugins, settings):
    """Print the analysis report."""
    print()
    print(colored("╔══════════════════════════════════════════════════╗", CYAN))
    print(colored("║       📊 Claude Code Session Analysis           ║", CYAN + BOLD))
    print(colored("╚══════════════════════════════════════════════════╝", CYAN))
    print()

    # Overview
    print(colored("  ═══ Overview ═══", YELLOW + BOLD))
    print(f"  Total history entries: {colored(str(stats['total_sessions']), WHITE + BOLD)}")

    if stats["first_session"] and stats["last_session"]:
        span = (stats["last_session"] - stats["first_session"]).days
        print(f"  Date range: {colored(stats['first_session'].strftime('%Y-%m-%d'), CYAN)} → "
              f"{colored(stats['last_session'].strftime('%Y-%m-%d'), CYAN)} ({span} days)")
    print()

    # Token usage
    print(colored("  ═══ Token Usage ═══", YELLOW + BOLD))
    total_in = stats["total_tokens_in"]
    total_out = stats["total_tokens_out"]
    total = total_in + total_out
    cost = format_cost(total_in, total_out)

    print(f"  Input tokens:  {colored(format_tokens(total_in), GREEN)}")
    print(f"  Output tokens: {colored(format_tokens(total_out), CYAN)}")
    print(f"  Total tokens:  {colored(format_tokens(total), WHITE + BOLD)}")
    print(f"  Est. cost:     {colored(f'${cost:.2f}', YELLOW + BOLD)}")
    print()

    # Tool usage
    if stats["tools_used"]:
        print(colored("  ═══ Top Tools ═══", YELLOW + BOLD))
        top_tools = stats["tools_used"].most_common(15)
        max_count = top_tools[0][1] if top_tools else 1
        for tool, count in top_tools:
            bar = bar_chart(count, max_count, 20)
            print(f"  {tool:<25} {bar} {count}")
        print()

    # Models
    if stats["models_used"]:
        print(colored("  ═══ Models ═══", YELLOW + BOLD))
        for model, count in stats["models_used"].most_common(5):
            print(f"  {colored(model, CYAN)}: {count} uses")
        print()

    # Activity by hour
    if stats["sessions_by_hour"]:
        print(colored("  ═══ Activity by Hour ═══", YELLOW + BOLD))
        max_hour = max(stats["sessions_by_hour"].values()) if stats["sessions_by_hour"] else 1
        for hour in range(24):
            count = stats["sessions_by_hour"].get(hour, 0)
            bar_len = int(20 * count / max(1, max_hour))
            bar_str = f"{GREEN}{'█' * bar_len}{RESET}"
            print(f"  {hour:02d}:00 {bar_str} {count}")
        print()

    # Projects
    if stats["projects"]:
        print(colored("  ═══ Top Projects ═══", YELLOW + BOLD))
        for project, count in stats["projects"].most_common(10):
            print(f"  {colored(project, CYAN)}: {count} sessions")
        print()

    # Installed plugins
    if plugins:
        print(colored("  ═══ Installed Plugins ═══", YELLOW + BOLD))
        for p in sorted(plugins):
            print(f"  📦 {colored(p, GREEN)}")
        print()

    # Project directories
    if projects:
        print(colored("  ═══ Project Configs ═══", YELLOW + BOLD))
        for p in sorted(projects, key=lambda x: x["name"]):
            file_count = len(p["files"])
            print(f"  📁 {colored(p['name'], CYAN)} ({file_count} files)")
        print()

    # Settings summary
    if settings:
        print(colored("  ═══ Settings ═══", YELLOW + BOLD))
        hooks = settings.get("hooks", {})
        perms = settings.get("permissions", {})
        if hooks:
            print(f"  Hooks configured: {colored(str(len(hooks)), GREEN)}")
            for hook_name in hooks:
                print(f"    ↪ {hook_name}")
        if perms:
            allow = perms.get("allow", [])
            deny = perms.get("deny", [])
            print(f"  Permissions: {colored(str(len(allow)), GREEN)} allow, {colored(str(len(deny)), RED)} deny")
        print()

    # Fun stats
    print(colored("  ═══ Fun Stats ═══", YELLOW + BOLD))
    if total_out > 0:
        words = total_out // 4  # ~4 tokens per word
        pages = words // 250
        print(f"  Claude wrote ~{colored(f'{words:,}', WHITE+BOLD)} words ({pages:,} pages)")
    if stats["sessions_by_day"]:
        active_days = len(stats["sessions_by_day"])
        max_day = max(stats["sessions_by_day"].items(), key=lambda x: x[1])
        print(f"  Active days: {colored(str(active_days), GREEN)}")
        print(f"  Busiest day: {colored(max_day[0], CYAN)} ({max_day[1]} entries)")
    print()


def main():
    print(colored("\n  📊 Scanning Claude Code data...\n", CYAN))

    # Check if Claude Code is installed
    if not CLAUDE_DIR.exists():
        print(colored("  ❌ Claude Code directory not found at ~/.claude/", RED))
        print(colored("  Make sure Claude Code is installed.\n", GRAY))
        return

    sessions = load_history()
    stats = analyze_sessions(sessions)
    projects = scan_projects()
    plugins = scan_plugins()
    settings = scan_settings()

    print_report(stats, projects, plugins, settings)


if __name__ == "__main__":
    main()
