#!/usr/bin/env python3
"""
cc-inspector.py  --  Claude Code Installation Inspector & Feature Flag Analyzer

Inspects your local Claude Code installation, extracts feature flags from the
compiled bundle, and reports on configuration, plugins, sessions, and more.

Standalone script -- stdlib only, no dependencies.
"""

import json
import os
import re
import subprocess
import sys
import glob as globmod
import time
from pathlib import Path
from collections import OrderedDict

# ──────────────────────────────────────────────────────────────────────────────
# ANSI color helpers
# ──────────────────────────────────────────────────────────────────────────────

class C:
    """ANSI color codes. Falls back to empty strings if NO_COLOR is set."""
    _enabled = sys.stdout.isatty() and "NO_COLOR" not in os.environ

    RESET   = "\033[0m"   if _enabled else ""
    BOLD    = "\033[1m"    if _enabled else ""
    DIM     = "\033[2m"    if _enabled else ""
    ITALIC  = "\033[3m"    if _enabled else ""
    ULINE   = "\033[4m"    if _enabled else ""

    BLACK   = "\033[30m"   if _enabled else ""
    RED     = "\033[31m"   if _enabled else ""
    GREEN   = "\033[32m"   if _enabled else ""
    YELLOW  = "\033[33m"   if _enabled else ""
    BLUE    = "\033[34m"   if _enabled else ""
    MAGENTA = "\033[35m"   if _enabled else ""
    CYAN    = "\033[36m"   if _enabled else ""
    WHITE   = "\033[37m"   if _enabled else ""

    BG_RED    = "\033[41m" if _enabled else ""
    BG_GREEN  = "\033[42m" if _enabled else ""
    BG_YELLOW = "\033[43m" if _enabled else ""
    BG_BLUE   = "\033[44m" if _enabled else ""
    BG_CYAN   = "\033[46m" if _enabled else ""
    BG_WHITE  = "\033[47m" if _enabled else ""

    BRIGHT_BLACK   = "\033[90m" if _enabled else ""
    BRIGHT_RED     = "\033[91m" if _enabled else ""
    BRIGHT_GREEN   = "\033[92m" if _enabled else ""
    BRIGHT_YELLOW  = "\033[93m" if _enabled else ""
    BRIGHT_BLUE    = "\033[94m" if _enabled else ""
    BRIGHT_MAGENTA = "\033[95m" if _enabled else ""
    BRIGHT_CYAN    = "\033[96m" if _enabled else ""
    BRIGHT_WHITE   = "\033[97m" if _enabled else ""


def banner():
    print(f"""
{C.BRIGHT_CYAN}{C.BOLD}  ╔══════════════════════════════════════════════════════════════╗
  ║           {C.BRIGHT_WHITE}cc-inspector{C.BRIGHT_CYAN}  --  Claude Code Analyzer            ║
  ║           {C.DIM}{C.CYAN}Feature Flags  |  Config  |  Bundle Scan{C.RESET}{C.BRIGHT_CYAN}{C.BOLD}          ║
  ╚══════════════════════════════════════════════════════════════╝{C.RESET}
""")


def section(title, icon=""):
    w = 62
    pad = w - len(title) - len(icon) - 2
    print(f"\n{C.BOLD}{C.BG_BLUE}{C.WHITE} {icon} {title}{' ' * max(pad, 1)}{C.RESET}")


def subsection(title):
    print(f"\n  {C.BOLD}{C.YELLOW}{title}{C.RESET}")
    print(f"  {C.DIM}{'─' * 56}{C.RESET}")


def kv(key, value, indent=4, key_color=C.CYAN, val_color=C.WHITE):
    spaces = " " * indent
    print(f"{spaces}{key_color}{key:<30}{C.RESET} {val_color}{value}{C.RESET}")


def kv_bool(key, enabled, indent=4):
    if enabled:
        val = f"{C.BRIGHT_GREEN}ENABLED{C.RESET}"
    else:
        val = f"{C.DIM}disabled{C.RESET}"
    kv(key, val, indent=indent)


def warn(msg):
    print(f"  {C.YELLOW}! {msg}{C.RESET}")


def info(msg):
    print(f"  {C.DIM}{msg}{C.RESET}")


def pill(text, bg=C.BG_CYAN, fg=C.BLACK):
    return f"{bg}{fg} {text} {C.RESET}"


# ──────────────────────────────────────────────────────────────────────────────
# Discovery
# ──────────────────────────────────────────────────────────────────────────────

def find_claude_binary():
    """Find the claude binary path."""
    try:
        # Use 'type' to resolve through aliases
        result = subprocess.run(
            ["bash", "-lc", "type -P claude 2>/dev/null || which claude 2>/dev/null"],
            capture_output=True, text=True, timeout=5
        )
        path = result.stdout.strip()
        if path and os.path.exists(path):
            return path
    except Exception:
        pass
    # Fallback: common locations
    for candidate in [
        os.path.expanduser("~/.nvm/versions/node/*/bin/claude"),
        "/opt/homebrew/bin/claude",
        "/usr/local/bin/claude",
    ]:
        matches = globmod.glob(candidate)
        if matches:
            return matches[0]
    return None


def find_package_dir():
    """Find the Claude Code npm package directory."""
    home = os.path.expanduser("~")
    # Check nvm
    nvm_pattern = os.path.join(home, ".nvm/versions/node/*/lib/node_modules/@anthropic-ai/claude-code")
    matches = sorted(globmod.glob(nvm_pattern), reverse=True)
    if matches:
        return matches[0]
    # Homebrew
    for base in ["/opt/homebrew/lib", "/usr/local/lib"]:
        p = os.path.join(base, "node_modules/@anthropic-ai/claude-code")
        if os.path.isdir(p):
            return p
    return None


def get_version(pkg_dir=None):
    """Get Claude Code version from package.json first, then CLI fallback."""
    # Prefer package.json -- always accurate
    if pkg_dir:
        pkg_json = read_json(os.path.join(pkg_dir, "package.json"))
        if pkg_json and "version" in pkg_json:
            return pkg_json["version"]
    # Fallback: run CLI
    try:
        result = subprocess.run(
            ["bash", "-lc", "claude --version 2>/dev/null"],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line and line[0].isdigit():
                return line.split()[0]  # strip " (Claude Code)" suffix
    except Exception:
        pass
    return None


def read_json(path):
    """Safely read a JSON file."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def read_text(path):
    """Safely read a text file."""
    try:
        with open(path, "r") as f:
            return f.read()
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Bundle analysis
# ──────────────────────────────────────────────────────────────────────────────

# Known feature flag descriptions from community analysis
KNOWN_FLAGS = {
    "tengu_amber_flint": "Subagent / swarm orchestration system -- enables multi-agent task dispatch",
    "tengu_amber_json_tools": "JSON-structured tool calling for agents",
    "tengu_amber_prism": "Enhanced agent visibility / transparency layer",
    "tengu_amber_quartz_disabled": "Kill switch for quartz agent subsystem",
    "tengu_amber_stoat": "Agent task routing / distribution",
    "tengu_amber_wren": "Agent communication channel",
    "tengu_auto_background_agents": "Auto-spawn background agents for parallel work",
    "tengu_bridge_client_presence_enabled": "Client presence tracking for bridge sessions",
    "tengu_bridge_repl_v2": "Next-gen REPL bridge protocol",
    "tengu_bridge_system_init": "Bridge system initialization flag",
    "tengu_bramble_lintel": "Unknown internal feature (codename obfuscated)",
    "tengu_ccr_bridge": "Claude Code Remote bridge connectivity",
    "tengu_chomp_inflection": "Response style / inflection control",
    "tengu_chrome_auto_enable": "Auto-enable Chrome/browser integration",
    "tengu_cicada_nap_ms": "Idle polling interval (ms) for background tasks",
    "tengu_cobalt_frost": "Unknown internal feature (codename obfuscated)",
    "tengu_cobalt_lantern": "Unknown internal feature (codename obfuscated)",
    "tengu_cold_compact": "Aggressive context compaction for cold sessions",
    "tengu_collage_kaleidoscope": "Multi-view UI rendering system",
    "tengu_compact_cache_prefix": "Prompt cache optimization for compaction",
    "tengu_compact_line_prefix_killswitch": "Kill switch for line-prefix compaction",
    "tengu_compact_streaming_retry": "Retry streaming on compaction failure",
    "tengu_copper_bridge": "Alternative bridge protocol",
    "tengu_coral_fern": "Unknown internal feature (codename obfuscated)",
    "tengu_cork_m4q": "Unknown internal feature (codename obfuscated)",
    "tengu_destructive_command_warning": "Warn before destructive bash commands",
    "tengu_disable_keepalive_on_econnreset": "Network resilience: disable keepalive on reset",
    "tengu_disable_streaming_to_non_streaming_fallback": "Disable fallback from streaming to non-streaming API",
    "tengu_edit_minimalanchor_jrn": "Minimal anchor strategy for file edits",
    "tengu_editafterwrite_qpl": "Allow edit immediately after write",
    "tengu_fgts": "Fine-grained tool streaming",
    "tengu_garnet_plover": "Unknown internal feature (codename obfuscated)",
    "tengu_glacier_2xr": "Unknown internal feature (codename obfuscated)",
    "tengu_gleaming_fair": "Unknown internal feature (codename obfuscated)",
    "tengu_gypsum_kite": "Unknown internal feature (codename obfuscated)",
    "tengu_harbor": "Harbor deployment / remote execution system",
    "tengu_harbor_permissions": "Permission model for Harbor remote sessions",
    "tengu_hawthorn_steeple": "Unknown internal feature (codename obfuscated)",
    "tengu_herring_clock": "Unknown internal feature (codename obfuscated)",
    "tengu_immediate_model_command": "Instant model switching via /model command",
    "tengu_jade_anvil_4": "Unknown internal feature (codename obfuscated)",
    "tengu_kairos_brief": "Kairos autonomous daemon -- brief/summary mode",
    "tengu_keybinding_customization_release": "Custom keybinding support release gate",
    "tengu_lapis_finch": "Unknown internal feature (codename obfuscated)",
    "tengu_lean_sub_pf7q": "Lean subagent prompt -- reduced context for child agents",
    "tengu_lodestone_enabled": "Lodestone navigation / code indexing system",
    "tengu_maple_forge_w8k": "Enhanced tool description / forge system",
    "tengu_marble_sandcastle": "Unknown internal feature (codename obfuscated)",
    "tengu_mcp_subagent_prompt": "MCP-aware subagent prompting",
    "tengu_miraculo_the_bard": "Unknown internal feature (creative codename)",
    "tengu_moth_copse": "Unknown internal feature (codename obfuscated)",
    "tengu_noreread_q7m_velvet": "Skip re-reading files already in context",
    "tengu_otk_slot_v1": "One-time key slot system v1",
    "tengu_paper_halyard": "Unknown internal feature (codename obfuscated)",
    "tengu_passport_quail": "Unknown internal feature (codename obfuscated)",
    "tengu_pebble_leaf_prune": "Context pruning / leaf node removal",
    "tengu_pid_based_version_locking": "Process-level version locking to prevent conflicts",
    "tengu_plan_mode_interview_phase": "Interactive interview phase in plan mode",
    "tengu_plugin_official_mkt_git_fallback": "Git fallback for official marketplace plugins",
    "tengu_plum_vx3": "Unknown internal feature (codename obfuscated)",
    "tengu_quartz_lantern": "Unknown internal feature (codename obfuscated)",
    "tengu_quiet_fern": "Unknown internal feature (codename obfuscated)",
    "tengu_read_dedup_killswitch": "Kill switch for file read deduplication",
    "tengu_relpath_gh7k": "Relative path handling improvement",
    "tengu_remote_backend": "Remote backend execution for Claude Code",
    "tengu_session_memory": "Per-session memory persistence",
    "tengu_slate_finch": "Unknown internal feature (codename obfuscated)",
    "tengu_slate_prism": "Enhanced UI rendering / prism display system",
    "tengu_slate_reef": "Unknown internal feature (codename obfuscated)",
    "tengu_slate_thimble": "Unknown internal feature (codename obfuscated)",
    "tengu_slim_subagent_claudemd": "Reduced CLAUDE.md injection for subagents",
    "tengu_sm_compact": "Session memory compaction",
    "tengu_sub_nomdrep_q7k": "Subagent nominal dedup optimization",
    "tengu_surreal_dali": "Unknown internal feature (creative codename)",
    "tengu_terminal_sidebar": "Terminal sidebar UI panel",
    "tengu_tern_alloy": "Multi-mode feature (off/on variants)",
    "tengu_tide_elm": "Multi-mode feature (off/on variants)",
    "tengu_timber_lark": "Multi-mode feature (off/on variants)",
    "tengu_trace_lantern": "Execution tracing / observability",
    "tengu_turtle_carbon": "Carbon footprint / efficiency tracking",
    "tengu_ultraplan_timeout_seconds": "Ultraplan remote planning timeout (seconds)",
    "tengu_vscode_cc_auth": "VS Code Claude Code authentication",
    "tengu_willow_mode": "Willow interaction mode (off/on variants)",
    "tengu_willow_prism": "Willow UI rendering variant",
    "enhanced_telemetry_beta": "Enhanced telemetry collection (beta)",
    "tengu_agent_list_attach": "Attach agent list to messages",
    "tengu_bridge_repl_v2_cse_shim_enabled": "CSE shim for bridge REPL v2",
    "tengu_attribution_header": "API attribution header inclusion",
}

# Known slash commands with descriptions
KNOWN_SLASH_COMMANDS = {
    "/agents": "Manage and view subagents",
    "/buddy": "Tamagotchi-style pet companion system",
    "/chrome": "Browser integration / Claude in Chrome",
    "/clear": "Clear conversation history",
    "/compact": "Compact conversation context",
    "/commit": "Create a git commit",
    "/commit-push-pr": "Commit, push, and create a PR",
    "/desktop": "Switch to Claude Code Desktop",
    "/dev": "Ad-hoc development workflow",
    "/effort": "Set thinking effort level",
    "/exit": "Exit Claude Code",
    "/extra-usage": "View/manage extra usage credits",
    "/fast": "Toggle fast mode (Haiku)",
    "/feedback": "Submit feedback",
    "/hooks": "Manage hooks configuration",
    "/init": "Initialize a new project",
    "/install-github-app": "Install GitHub App for CI",
    "/login": "Authenticate with Anthropic",
    "/logout": "Log out",
    "/loop": "Run a prompt on a recurring interval",
    "/mcp": "Manage MCP servers",
    "/memory": "View/edit memory files",
    "/model": "Switch AI model",
    "/passes": "View guest passes",
    "/permissions": "Manage permissions",
    "/plugin": "Manage plugins",
    "/powerup": "Interactive tutorial / tips",
    "/rate-limit-options": "View rate limit handling options",
    "/remote-control": "Remote control from phone",
    "/review-pr": "Review a pull request",
    "/rewind": "Rewind conversation to earlier point",
    "/skills": "View available skills",
    "/stats": "Session statistics",
    "/status": "View system status",
    "/tasks": "View background tasks",
    "/teleport": "Pull a web session into terminal",
    "/ultrareview": "Ultra-deep PR review (remote)",
}


def analyze_bundle(bundle_path):
    """Extract feature flags and interesting strings from the CLI bundle."""
    content = read_text(bundle_path)
    if not content:
        return None

    results = {}

    # 1. Feature flags via L8("name", default)
    flag_pattern = re.compile(r'L8\("([^"]+)",\s*(!?[01]|true|false|"[^"]*"|\d+)\)')
    flags = {}
    for match in flag_pattern.finditer(content):
        name, default = match.group(1), match.group(2)
        # Normalize defaults
        if default == "!0" or default == "true":
            enabled = True
        elif default == "!1" or default == "false":
            enabled = False
        elif default.isdigit():
            enabled = int(default)
        else:
            enabled = default.strip('"')
        flags[name] = enabled
    results["flags"] = OrderedDict(sorted(flags.items()))

    # 2. All tengu_ event/metric strings
    tengu_strings = sorted(set(re.findall(r'tengu_[a-zA-Z0-9_]+', content)))
    results["tengu_all"] = tengu_strings

    # 3. Model identifiers
    model_ids = sorted(set(re.findall(r'"(claude-[a-zA-Z0-9._-]+)"', content)))
    results["model_ids"] = model_ids

    # 4. API endpoints
    api_endpoints = sorted(set(re.findall(r'"(https?://api[^"]+)"', content)))
    results["api_endpoints"] = api_endpoints

    # 5. Environment variables
    env_vars = sorted(set(re.findall(r'process\.env\.([A-Z_][A-Z0-9_]+)', content)))
    results["env_vars"] = env_vars

    # 6. Slash commands
    slash_cmds = sorted(set(re.findall(r'"(/[a-z][a-z_-]+)"', content)))
    # Filter to likely real commands (not paths like /usr, /bin, etc.)
    system_paths = {"/bin", "/dev", "/etc", "/lib", "/opt", "/proc", "/sbin",
                    "/sh", "/tmp", "/usr", "/var", "/zsh", "/fish",
                    "/ld-linux-", "/ld-musl-", "/npx", "/fo", "/ve", "/nh",
                    "/priv", "/private", "/all", "/allcompartments", "/change",
                    "/create", "/delete-foundation-model-agreement",
                    "/create-foundation-model-agreement", "/custom-models",
                    "/deploy", "/evaluation-jobs", "/events", "/foundation-models",
                    "/groups", "/guardrails", "/imported-models", "/inference-profiles",
                    "/model-copy-jobs", "/model-customization-jobs", "/model-import-jobs",
                    "/model-invocation-job", "/model-invocation-jobs", "/properties",
                    "/provisioned-model-throughput", "/provisioned-model-throughputs",
                    "/prompt-routers", "/use-case-for-model-access", "/user",
                    "/claims", "/logonid", "/register", "/devicecode", "/authorize",
                    "/token", "/transfer", "/callback", "/async-invoke",
                    "/automated-reasoning-policies", "/worker", "/stream",
                    "/sse", "/btw", "/emcc", "/issue", "/branch", "/dashboard",
                    "/urlcache", "/metrics"}
    real_cmds = [c for c in slash_cmds if c not in system_paths]
    results["slash_commands"] = real_cmds

    # 7. Source map check
    results["has_source_map"] = (
        os.path.exists(bundle_path + ".map") or
        "sourceMappingURL" in content[-500:]
    )

    # 8. Bundle stats
    results["bundle_size"] = os.path.getsize(bundle_path)
    results["bundle_lines"] = content.count("\n") + 1

    # 9. Interesting string patterns
    interesting = {}

    # Codename patterns (nature-themed)
    codenames = sorted(set(re.findall(
        r'tengu_(?:amber|bramble|chair|chomp|cobalt|cold|collage|copper|coral|cork|'
        r'dunwich|frond|garnet|glacier|gleaming|grey|gypsum|harbor|hawthorn|herring|'
        r'jade|kairos|lapis|lodestone|malort|maple|marble|miraculo|moth|noreread|'
        r'onyx|otk|paper|passport|pebble|pewter|plum|quartz|quiet|sage|satin|'
        r'slate|surreal|tern|tide|timber|trace|turtle|ultraplan|ultrathink|'
        r'willow)[_a-zA-Z0-9]*',
        content
    )))
    interesting["codename_flags"] = codenames

    # Dream/memory related
    dream_strings = sorted(set(re.findall(r'["\']([^"\']*(?:dream|memory|memdir)[^"\']*)["\']', content)))
    interesting["dream_memory"] = [s for s in dream_strings if len(s) < 60 and "tengu" not in s][:20]

    results["interesting"] = interesting

    return results


# ──────────────────────────────────────────────────────────────────────────────
# Report rendering
# ──────────────────────────────────────────────────────────────────────────────

def render_installation(pkg_dir, version):
    section("INSTALLATION", icon=">>")

    kv("Version", f"{C.BRIGHT_GREEN}{C.BOLD}{version or 'unknown'}{C.RESET}")
    kv("Package directory", pkg_dir or "not found")

    cli_js = os.path.join(pkg_dir, "cli.js") if pkg_dir else None
    if cli_js and os.path.exists(cli_js):
        size_mb = os.path.getsize(cli_js) / (1024 * 1024)
        kv("Bundle", f"cli.js ({size_mb:.1f} MB)")
    else:
        kv("Bundle", f"{C.RED}not found{C.RESET}")

    claude_dir = os.path.expanduser("~/.claude")
    kv("Config directory", claude_dir if os.path.isdir(claude_dir) else "not found")

    # Check source maps
    if cli_js:
        has_map = os.path.exists(cli_js + ".map")
        if has_map:
            kv("Source maps", f"{C.BRIGHT_RED}{C.BOLD}PRESENT (the leak!){C.RESET}")
        else:
            kv("Source maps", f"{C.DIM}not present{C.RESET}")

    # Vendor
    vendor_dir = os.path.join(pkg_dir, "vendor") if pkg_dir else None
    if vendor_dir and os.path.isdir(vendor_dir):
        vendors = os.listdir(vendor_dir)
        kv("Vendor modules", ", ".join(vendors))


def render_feature_flags(analysis):
    section("FEATURE FLAGS", icon=">>")

    flags = analysis.get("flags", {})
    if not flags:
        warn("No feature flags found in bundle")
        return

    # Separate by state
    enabled_flags = {k: v for k, v in flags.items() if v is True or v == "on"}
    disabled_flags = {k: v for k, v in flags.items() if v is False or v == "off"}
    numeric_flags = {k: v for k, v in flags.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    string_flags = {k: v for k, v in flags.items() if isinstance(v, str) and v not in ("on", "off")}

    total = len(flags)
    print(f"\n  {C.DIM}Found {C.BOLD}{C.WHITE}{total}{C.RESET}{C.DIM} feature flags "
          f"({C.GREEN}{len(enabled_flags)} enabled{C.DIM}, "
          f"{C.RED}{len(disabled_flags)} disabled{C.DIM}, "
          f"{C.YELLOW}{len(numeric_flags) + len(string_flags)} configured{C.DIM}){C.RESET}")

    subsection(f"ENABLED ({len(enabled_flags)})")
    for name in sorted(enabled_flags.keys()):
        desc = KNOWN_FLAGS.get(name, "")
        tag = f" {C.BRIGHT_GREEN}ON{C.RESET}"
        desc_str = f"  {C.DIM}{desc}{C.RESET}" if desc else ""
        print(f"    {tag}  {C.WHITE}{name}{C.RESET}{desc_str}")

    subsection(f"DISABLED ({len(disabled_flags)})")
    for name in sorted(disabled_flags.keys()):
        desc = KNOWN_FLAGS.get(name, "")
        tag = f"{C.DIM}OFF{C.RESET}"
        desc_str = f"  {C.DIM}{desc}{C.RESET}" if desc else ""
        print(f"    {tag}  {C.DIM}{name}{C.RESET}{desc_str}")

    if numeric_flags or string_flags:
        subsection(f"CONFIGURED ({len(numeric_flags) + len(string_flags)})")
        for name, val in sorted({**numeric_flags, **string_flags}.items()):
            desc = KNOWN_FLAGS.get(name, "")
            desc_str = f"  {C.DIM}{desc}{C.RESET}" if desc else ""
            print(f"    {C.YELLOW}{val:>6}{C.RESET}  {C.WHITE}{name}{C.RESET}{desc_str}")


def render_flag_highlights(analysis):
    section("NOTABLE FLAGS DEEP DIVE", icon=">>")

    flags = analysis.get("flags", {})
    highlights = [
        ("tengu_amber_flint", "SWARMS / SUBAGENTS",
         "Multi-agent orchestration. When enabled, Claude can spawn child agents for parallel tasks."),
        ("tengu_kairos_brief", "KAIROS DAEMON",
         "Autonomous background daemon mode. Allows Claude to run scheduled/recurring tasks."),
        ("tengu_harbor", "HARBOR / REMOTE",
         "Remote execution backend. Run Claude Code sessions on remote infrastructure."),
        ("tengu_terminal_sidebar", "TERMINAL SIDEBAR",
         "Side panel UI in terminal. New interface layout."),
        ("tengu_session_memory", "SESSION MEMORY",
         "Per-session memory that persists across compactions."),
        ("tengu_remote_backend", "REMOTE BACKEND",
         "Remote API backend for Claude Code operations."),
        ("tengu_auto_background_agents", "AUTO BACKGROUND AGENTS",
         "Automatically spawn background agents for independent tasks."),
        ("tengu_sm_compact", "SESSION MEMORY COMPACTION",
         "Smart compaction of session memory for longer sessions."),
        ("tengu_chrome_auto_enable", "CHROME AUTO-ENABLE",
         "Automatically enable Claude in Chrome browser."),
        ("tengu_plan_mode_interview_phase", "PLAN INTERVIEW",
         "Interactive interview phase when creating plans."),
        ("tengu_lodestone_enabled", "LODESTONE INDEXING",
         "Code indexing system for faster searches."),
        ("tengu_destructive_command_warning", "DESTRUCTIVE CMD WARNING",
         "Warning before executing destructive shell commands."),
    ]

    for flag_name, label, description in highlights:
        val = flags.get(flag_name)
        if val is None:
            status = f"{C.DIM}NOT FOUND{C.RESET}"
        elif val is True:
            status = f"{C.BRIGHT_GREEN}{C.BOLD}ENABLED{C.RESET}"
        elif val is False:
            status = f"{C.BRIGHT_RED}DISABLED{C.RESET}"
        else:
            status = f"{C.YELLOW}{val}{C.RESET}"

        print(f"\n  {C.BOLD}{C.CYAN}{label}{C.RESET}  [{status}]")
        print(f"    {C.DIM}Flag: {flag_name}{C.RESET}")
        print(f"    {C.DIM}{description}{C.RESET}")


def render_telemetry_strings(analysis):
    section("TELEMETRY / EVENT STRINGS", icon=">>")

    tengu_all = analysis.get("tengu_all", [])
    flags = analysis.get("flags", {})
    flag_names = set(flags.keys())

    # Events = tengu strings that are NOT feature flags
    events = [t for t in tengu_all if t not in flag_names]

    print(f"\n  {C.DIM}Total tengu_* strings in bundle: {C.WHITE}{C.BOLD}{len(tengu_all)}{C.RESET}")
    print(f"  {C.DIM}Feature flags: {C.WHITE}{len(flag_names)}{C.RESET}")
    print(f"  {C.DIM}Telemetry events/metrics: {C.WHITE}{len(events)}{C.RESET}")

    # Group by prefix
    categories = {}
    for e in events:
        parts = e.split("_", 2)  # tengu_category_rest
        if len(parts) >= 3:
            cat = parts[1]
        else:
            cat = "other"
        categories.setdefault(cat, []).append(e)

    subsection("Top event categories")
    sorted_cats = sorted(categories.items(), key=lambda x: -len(x[1]))
    for cat, items in sorted_cats[:20]:
        bar_len = min(len(items), 40)
        bar = f"{C.CYAN}{'|' * bar_len}{C.RESET}"
        print(f"    {C.WHITE}{cat:<24}{C.RESET} {bar} {C.DIM}{len(items)}{C.RESET}")


def render_models(analysis):
    section("MODEL IDENTIFIERS", icon=">>")

    model_ids = analysis.get("model_ids", [])
    # Filter to actual model versions
    real_models = [m for m in model_ids if re.match(r'^claude-\d', m) or
                   re.match(r'^claude-(opus|sonnet|haiku|instant)', m)]
    other_ids = [m for m in model_ids if m not in real_models]

    subsection(f"Model versions ({len(real_models)})")
    for m in real_models:
        # Highlight unreleased / interesting models
        if any(x in m for x in ["4-5", "4-6", "opus-4-1"]):
            print(f"    {C.BRIGHT_MAGENTA}{C.BOLD}{m}{C.RESET}  {C.YELLOW}<-- newer model{C.RESET}")
        elif "opus" in m:
            print(f"    {C.BRIGHT_CYAN}{m}{C.RESET}")
        elif "sonnet" in m:
            print(f"    {C.BRIGHT_GREEN}{m}{C.RESET}")
        elif "haiku" in m:
            print(f"    {C.BRIGHT_YELLOW}{m}{C.RESET}")
        else:
            print(f"    {C.DIM}{m}{C.RESET}")

    if other_ids:
        subsection(f"Other claude-* identifiers ({len(other_ids)})")
        for m in other_ids:
            print(f"    {C.DIM}{m}{C.RESET}")


def render_api_endpoints(analysis):
    section("API ENDPOINTS", icon=">>")

    endpoints = analysis.get("api_endpoints", [])
    for ep in endpoints:
        if "staging" in ep:
            print(f"    {C.YELLOW}{ep}{C.RESET}  {C.DIM}(staging){C.RESET}")
        else:
            print(f"    {C.WHITE}{ep}{C.RESET}")


def render_env_vars(analysis):
    section("ENVIRONMENT VARIABLES", icon=">>")

    env_vars = analysis.get("env_vars", [])

    # Categorize
    categories = {
        "Anthropic Core": [v for v in env_vars if v.startswith("ANTHROPIC_")],
        "Claude Code": [v for v in env_vars if v.startswith("CLAUDE_CODE_") or v.startswith("CLAUDE_")],
        "Cloud/Auth (AWS)": [v for v in env_vars if v.startswith("AWS_")],
        "Cloud/Auth (Azure)": [v for v in env_vars if v.startswith("AZURE_")],
        "Cloud/Auth (GCP)": [v for v in env_vars if v.startswith("GOOGLE_") or v.startswith("GCE_") or v.startswith("GCLOUD_")],
        "MCP": [v for v in env_vars if v.startswith("MCP_")],
        "OpenTelemetry": [v for v in env_vars if v.startswith("OTEL_")],
        "Feature Toggles": [v for v in env_vars if v.startswith("DISABLE_") or v.startswith("ENABLE_")],
    }

    for cat, vars_list in categories.items():
        if vars_list:
            subsection(f"{cat} ({len(vars_list)})")
            for v in vars_list[:15]:
                # Check if set in current env
                is_set = os.environ.get(v) is not None
                indicator = f"{C.GREEN}SET{C.RESET}" if is_set else f"{C.DIM}---{C.RESET}"
                print(f"    {indicator}  {C.WHITE}{v}{C.RESET}")
            if len(vars_list) > 15:
                print(f"    {C.DIM}... and {len(vars_list) - 15} more{C.RESET}")

    print(f"\n  {C.DIM}Total env vars referenced: {C.WHITE}{len(env_vars)}{C.RESET}")


def render_slash_commands(analysis):
    section("SLASH COMMANDS", icon=">>")

    cmds = analysis.get("slash_commands", [])

    for cmd in cmds:
        desc = KNOWN_SLASH_COMMANDS.get(cmd, "")
        if desc:
            print(f"    {C.CYAN}{cmd:<25}{C.RESET} {C.DIM}{desc}{C.RESET}")
        else:
            print(f"    {C.WHITE}{cmd}{C.RESET}")


def render_config(claude_dir):
    section("CONFIGURATION", icon=">>")

    # settings.json
    settings = read_json(os.path.join(claude_dir, "settings.json"))
    if settings:
        subsection("settings.json")
        # Hooks
        hooks = settings.get("hooks", {})
        if hooks:
            kv("Hooks configured", f"{len(hooks)} event(s)")
            for event_name, hook_list in hooks.items():
                hook_count = sum(len(h.get("hooks", [])) for h in hook_list) if isinstance(hook_list, list) else 0
                print(f"      {C.DIM}{event_name}: {hook_count} hook(s){C.RESET}")

        # Plugins
        plugins = settings.get("enabledPlugins", {})
        if plugins:
            enabled = [k for k, v in plugins.items() if v]
            kv("Plugins enabled", str(len(enabled)))
            for p in sorted(enabled):
                parts = p.split("@")
                name = parts[0]
                source = parts[1] if len(parts) > 1 else ""
                print(f"      {C.GREEN}+{C.RESET} {C.WHITE}{name}{C.RESET}  {C.DIM}@{source}{C.RESET}")

        # Extra marketplaces
        markets = settings.get("extraKnownMarketplaces", {})
        if markets:
            kv("Extra marketplaces", str(len(markets)))
            for name, data in markets.items():
                src = data.get("source", {}).get("repo", "")
                print(f"      {C.CYAN}{name}{C.RESET}  {C.DIM}{src}{C.RESET}")

        # Other settings
        other_keys = {k: v for k, v in settings.items()
                      if k not in ("hooks", "enabledPlugins", "extraKnownMarketplaces")}
        if other_keys:
            subsection("Other settings")
            for k, v in sorted(other_keys.items()):
                val_str = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                if len(val_str) > 60:
                    val_str = val_str[:57] + "..."
                kv(k, val_str)

    # settings.local.json
    local_settings = read_json(os.path.join(claude_dir, "settings.local.json"))
    if local_settings:
        subsection("settings.local.json")
        print(f"    {C.DIM}{json.dumps(local_settings, indent=2)[:300]}{C.RESET}")


def render_sessions(claude_dir):
    section("SESSIONS & HISTORY", icon=">>")

    # History
    history_path = os.path.join(claude_dir, "history.jsonl")
    if os.path.exists(history_path):
        size = os.path.getsize(history_path)
        with open(history_path) as f:
            lines = sum(1 for _ in f)
        kv("History entries", str(lines))
        kv("History size", f"{size / 1024:.1f} KB")

    # Sessions
    sessions_dir = os.path.join(claude_dir, "sessions")
    if os.path.isdir(sessions_dir):
        session_files = os.listdir(sessions_dir)
        kv("Session files", str(len(session_files)))

    # Debug logs
    debug_dir = os.path.join(claude_dir, "debug")
    if os.path.isdir(debug_dir):
        debug_files = os.listdir(debug_dir)
        kv("Debug log files", str(len(debug_files)))

    # Tasks
    tasks_dir = os.path.join(claude_dir, "tasks")
    if os.path.isdir(tasks_dir):
        task_files = os.listdir(tasks_dir)
        kv("Task files", str(len(task_files)))

    # Telemetry
    telemetry_dir = os.path.join(claude_dir, "telemetry")
    if os.path.isdir(telemetry_dir):
        tel_files = os.listdir(telemetry_dir)
        kv("Telemetry files", str(len(tel_files)))

    # Todos
    todos_dir = os.path.join(claude_dir, "todos")
    if os.path.isdir(todos_dir):
        todo_files = os.listdir(todos_dir)
        kv("Todo files", str(len(todo_files)))

    # Projects
    projects_dir = os.path.join(claude_dir, "projects")
    if os.path.isdir(projects_dir):
        project_dirs = [d for d in os.listdir(projects_dir) if not d.startswith(".")]
        kv("Project configs", str(len(project_dirs)))

    # File history / backups
    backups_dir = os.path.join(claude_dir, "backups")
    if os.path.isdir(backups_dir):
        backup_count = len(os.listdir(backups_dir))
        kv("Backup files", str(backup_count))

    fh_dir = os.path.join(claude_dir, "file-history")
    if os.path.isdir(fh_dir):
        fh_count = len(os.listdir(fh_dir))
        kv("File history snapshots", str(fh_count))


def render_codename_analysis(analysis):
    section("CODENAME ANALYSIS", icon=">>")

    codenames = analysis.get("interesting", {}).get("codename_flags", [])
    if not codenames:
        info("No codename flags found")
        return

    # Extract unique codename prefixes
    prefixes = {}
    for cn in codenames:
        parts = cn.split("_", 2)  # tengu_PREFIX_rest
        if len(parts) >= 3:
            prefix = parts[1]
            prefixes.setdefault(prefix, []).append(cn)

    print(f"\n  {C.DIM}Found {C.WHITE}{C.BOLD}{len(prefixes)}{C.RESET}{C.DIM} codename families, "
          f"{C.WHITE}{len(codenames)}{C.RESET}{C.DIM} total strings{C.RESET}\n")

    for prefix in sorted(prefixes.keys()):
        items = prefixes[prefix]
        flags = analysis.get("flags", {})
        # Check if any in this family are feature flags
        flag_items = [i for i in items if i in flags]
        event_items = [i for i in items if i not in flags]

        color = C.BRIGHT_MAGENTA if flag_items else C.DIM
        print(f"  {color}{prefix}{C.RESET}  ({len(items)} strings)")
        for item in flag_items:
            val = flags[item]
            if val is True:
                print(f"    {C.GREEN}[ON]{C.RESET}  {item}")
            elif val is False:
                print(f"    {C.RED}[--]{C.RESET}  {item}")
            else:
                print(f"    {C.YELLOW}[{val}]{C.RESET}  {item}")
        if event_items and len(event_items) <= 5:
            for item in event_items:
                print(f"    {C.DIM}      {item}{C.RESET}")
        elif event_items:
            print(f"    {C.DIM}      + {len(event_items)} event/metric strings{C.RESET}")


def render_summary(analysis, version):
    section("SUMMARY", icon=">>")

    flags = analysis.get("flags", {})
    enabled = sum(1 for v in flags.values() if v is True or v == "on")
    disabled = sum(1 for v in flags.values() if v is False or v == "off")

    print(f"""
  {C.BOLD}Claude Code {version or '?'}{C.RESET}

  {C.CYAN}Feature Flags{C.RESET}      {enabled} enabled / {disabled} disabled / {len(flags)} total
  {C.CYAN}Telemetry Events{C.RESET}   {len(analysis.get('tengu_all', []))} tengu_* strings
  {C.CYAN}Models{C.RESET}             {len(analysis.get('model_ids', []))} model identifiers
  {C.CYAN}API Endpoints{C.RESET}      {len(analysis.get('api_endpoints', []))} endpoints
  {C.CYAN}Env Vars{C.RESET}           {len(analysis.get('env_vars', []))} referenced
  {C.CYAN}Slash Commands{C.RESET}     {len(analysis.get('slash_commands', []))} detected
  {C.CYAN}Bundle Size{C.RESET}        {analysis.get('bundle_size', 0) / (1024*1024):.1f} MB ({analysis.get('bundle_lines', 0):,} lines)
  {C.CYAN}Source Maps{C.RESET}        {'PRESENT' if analysis.get('has_source_map') else 'not present'}

  {C.DIM}Report generated {time.strftime('%Y-%m-%d %H:%M:%S')}{C.RESET}
""")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Inspect your local Claude Code installation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cc-inspect                  Full report
  cc-inspect --flags          Feature flags only
  cc-inspect --models         Model identifiers only
  cc-inspect --env            Environment variables only
  cc-inspect --config         Configuration only
  cc-inspect --json           JSON output (all data)
        """
    )
    parser.add_argument("--flags", action="store_true", help="Show feature flags only")
    parser.add_argument("--models", action="store_true", help="Show model identifiers only")
    parser.add_argument("--env", action="store_true", help="Show environment variables only")
    parser.add_argument("--config", action="store_true", help="Show configuration only")
    parser.add_argument("--commands", action="store_true", help="Show slash commands only")
    parser.add_argument("--json", action="store_true", help="Output raw JSON data")
    parser.add_argument("--brief", action="store_true", help="Brief summary only")
    args = parser.parse_args()

    specific_section = args.flags or args.models or args.env or args.config or args.commands

    if not args.json:
        banner()

    # Find installation
    pkg_dir = find_package_dir()
    version = get_version(pkg_dir)
    claude_dir = os.path.expanduser("~/.claude")

    if not pkg_dir:
        print(f"{C.RED}ERROR: Could not find Claude Code installation.{C.RESET}")
        print(f"{C.DIM}Checked: ~/.nvm, /opt/homebrew, /usr/local{C.RESET}")
        sys.exit(1)

    cli_js = os.path.join(pkg_dir, "cli.js")
    if not os.path.exists(cli_js):
        print(f"{C.RED}ERROR: cli.js not found at {cli_js}{C.RESET}")
        sys.exit(1)

    # Analyze bundle
    if not args.json:
        print(f"  {C.DIM}Analyzing bundle at {cli_js}...{C.RESET}")
    analysis = analyze_bundle(cli_js)

    if not analysis:
        print(f"{C.RED}ERROR: Failed to analyze bundle{C.RESET}")
        sys.exit(1)

    # JSON output mode
    if args.json:
        # Make it JSON serializable
        output = {
            "version": version,
            "package_dir": pkg_dir,
            "flags": dict(analysis["flags"]),
            "tengu_event_count": len(analysis["tengu_all"]),
            "model_ids": analysis["model_ids"],
            "api_endpoints": analysis["api_endpoints"],
            "env_vars": analysis["env_vars"],
            "slash_commands": analysis["slash_commands"],
            "has_source_map": analysis["has_source_map"],
            "bundle_size": analysis["bundle_size"],
            "bundle_lines": analysis["bundle_lines"],
        }
        print(json.dumps(output, indent=2))
        return

    # Specific section mode
    if args.flags:
        render_feature_flags(analysis)
        render_flag_highlights(analysis)
        return
    if args.models:
        render_models(analysis)
        return
    if args.env:
        render_env_vars(analysis)
        return
    if args.config:
        render_config(claude_dir)
        return
    if args.commands:
        render_slash_commands(analysis)
        return

    # Brief mode
    if args.brief:
        render_summary(analysis, version)
        return

    # Full report
    render_installation(pkg_dir, version)
    render_feature_flags(analysis)
    render_flag_highlights(analysis)
    render_codename_analysis(analysis)
    render_models(analysis)
    render_api_endpoints(analysis)
    render_slash_commands(analysis)
    render_env_vars(analysis)
    render_config(claude_dir)
    render_sessions(claude_dir)
    render_telemetry_strings(analysis)
    render_summary(analysis, version)


if __name__ == "__main__":
    main()
