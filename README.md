# Realtime HALfred

A Python-based realtime voice assistant powered by OpenAI's Realtime API, OpenAI Responses API, and ElevenLabs TTS. HALfred is a sardonic, sharp-tongued AI companion with personality, natural voice conversations, screen analysis, and optional desktop automation through MCP integration.

> **Current architecture:** a low-latency Realtime "front desk" agent handles conversation and escalates tool-heavy work to a Supervisor agent. Prompt text is loaded from versioned files via `prompt_store.py`, and an optional metaprompt agent can propose prompt improvements during dormancy. See [docs/SUPERVISOR.md](docs/SUPERVISOR.md) and [docs/METAPROMPT.md](docs/METAPROMPT.md) for details.

## Quick Start

```bash
git clone --recursive https://github.com/edwardandrew-a11y/Realtime_HALfred.git
cd Realtime_HALfred
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cd ScreenMonitorMCP
pip install -e .
cd ..
cp .env.example .env
# Optional: only needed if you plan to enable ENABLE_FEEDBACK_LOOP_MCP=true
npm install
python main.py
```


## Overview

Realtime HALfred uses:
- **OpenAI Realtime API** (`gpt-realtime`) for low-latency voice I/O
- **OpenAI Responses API** (Supervisor) for complex tasks with built-in tools (`web_search`, `code_interpreter`, `image_generation`, and optional `file_search`)
- **ElevenLabs** for high-quality, natural text-to-speech output
- **ScreenMonitorMCP** for AI vision and screen analysis capabilities
- **PTY Terminal Access** for safe shell command execution with user confirmation
- **MCP (Model Context Protocol)** for extensible tool integration
- **Semantic VAD** for intelligent turn detection
- **Whisper-1** for microphone turn transcription
- **AnkiConnect + Anki subagent** for Anki-specific tasks routed through the Supervisor

## Features

- 🎙️ **Continuous Voice Interaction** - Toggle hands-free listening with `/mic` command
- 🎤 **Push-to-Talk Mode** - Hold your configured `PTT_KEY` combo or key to speak, release to send
- 🛑 **Speech Interruption** - Interrupt HALfred mid-response with `/stop` or PTT activation
- 🗣️ **Natural TTS** - ElevenLabs streaming audio for low-latency, natural speech
- 🎭 **Personality-Driven** - Halfred has a distinct personality: sardonic, helpful, and unfiltered
- 👁️ **Vision Capabilities** - Screen capture and AI-powered visual analysis through MCP
- 💻 **Terminal Access** - Safe shell command execution with command-level safety controls
- 🔧 **Extensible Tools** - MCP integration allows adding new capabilities easily
- 🎧 **Half-Duplex Audio** - Mic capture stops while HALfred is responding and resumes automatically in continuous mode
- 🧠 **Optional Metaprompt Optimization** - During dormancy, HALfred can review feedback and propose versioned prompt updates for human approval

## ⚠️ Important Notes

### Core Features (Stable)
The following features have been extensively tested and are production-ready:
- ✅ Voice interaction (OpenAI Realtime API + ElevenLabs TTS)
- ✅ Screen monitoring (ScreenMonitorMCP)
- ✅ PTY terminal access (pty-proxy-mcp)

### Optional Desktop Automation (macOS only)
- ✅ **`safe_action`** wraps `macos-automator-mcp` with mandatory confirmation
- ⚠️ **`feedback-loop-mcp` overlays** are still experimental and only load when `ENABLE_FEEDBACK_LOOP_MCP=true`
- ⚠️ **Target highlighting** is not yet implemented in `automation_safety.py`; the flow still uses screenshot + confirmation before actions
- ℹ️ **Setup note:** the checked-in `MCP_SERVERS.json` contains a machine-specific `macos-automator` path, so update it before enabling `ENABLE_MACOS_AUTOMATOR_MCP=true`

**Recommendations:**
- Test automation features in a safe environment first
- Use `DEV_MODE=true` and test commands (`/demo_click`, `/screeninfo`) before real usage
- Keep `AUTOMATION_REQUIRE_APPROVAL=true` to maintain safety
- Report issues to the project's GitHub issues page

## Available Tools

### Realtime Agent Tool
- **`escalate_to_supervisor`** - The Realtime agent's only tool; hands off screen, web, code, automation, terminal, and other multi-step tasks to the Supervisor

### Supervisor Built-in Tools
- **`web_search`** - Current information via the Responses API
- **`code_interpreter`** - Sandboxed Python execution
- **`image_generation`** - Image generation
- **`file_search`** - Optional RAG tool when `SUPERVISOR_VECTOR_STORE_ID` is configured

### Supervisor Native Tools
- **`local_time`** - Returns the current local time
- **`screencapture`** - Captures a screenshot and saves it locally
- **`safe_action`** - Optional macOS automation wrapper with confirmation
- **`anki_agent`** - Routes Anki tasks through the Anki subagent / AnkiConnect integration

### MCP Tools (ScreenMonitorMCP)
The ScreenMonitorMCP submodule provides screen-analysis, streaming, diagnostics, and memory tools. Common tools include:

1. **`analyze_screen`** - AI-powered screen content analysis and interpretation
2. **`detect_ui_elements`** - Identify UI elements on screen
3. **`assess_system_performance`** - Assess visible performance signals
4. **`create_stream` / `list_streams` / `get_stream_info`** - Manage live screen streams
5. **`query_memory` / `get_memory_statistics`** - Inspect stored stream memory and diagnostics
6. **`get_performance_metrics` / `get_system_status`** - Report system and server health

These tools enable Halfred to:
- See and describe what's on your screen
- Debug visual issues in applications
- Analyze UI/UX design
- Monitor system performance
- Assist with visual tasks and documentation

### MCP Tools (PTY Terminal Access)
Halfred has safe terminal access through the PTY proxy:

**`pty_bash_execute`** - Execute shell commands with command-level safety controls

**Safety Features:**
- **Safe commands** (pwd, ls, cat, grep, find, etc.) execute automatically without prompts
- **Risky commands** (mkdir, rm, chmod, network ops) require user confirmation when `PTY_REQUIRE_APPROVAL=true`
- **Dangerous commands** (rm -rf, sudo, dd) show strong warnings before execution
- Command parsing detects dangerous patterns (pipes to shell, output redirection, etc.)
- Setting `PTY_REQUIRE_APPROVAL=false` keeps PTY enabled but removes the confirmation prompts

**Safe Commands (Auto-Approved):**
- Navigation: `pwd`, `cd`, `ls`, `tree`, `find`
- Reading: `cat`, `less`, `more`, `head`, `tail`, `grep`
- Info: `stat`, `file`, `du`, `df`, `whoami`, `uname`, `id`

**Use Cases:**
- Navigate directories and inspect file contents
- Search for files and patterns
- Gather system information
- Debug file permissions and ownership
- Explore project structures

**Platform Support:**
- **macOS/Linux:** Uses `/bin/bash` for command execution
- **Windows:** Uses `cmd.exe` for command execution
- Safety controls work identically across all platforms

### Native Screenshot Tool (Supervisor)

**`screencapture`** - Fast, native OS screenshot capture registered as a Supervisor native tool

HALfred can use `screencapture` through the Supervisor to:
- Captures screenshots using OS-native APIs (macOS `screencapture`, Windows/Linux PIL)
- Saves images to `screenshots/` directory with timestamp filenames
- Returns metadata JSON (path, filename, dimensions, timestamp)
- Supports screenshot-taking and debug flows without embedding image bytes in tool output

For richer visual analysis, the Supervisor also has ScreenMonitorMCP tools such as `analyze_screen`.

**Example Usage:**
```
You> Save a screenshot of my current screen
HALfred> [escalates to Supervisor → Supervisor calls screencapture → reports the saved path]
```

**Platform Support:**
- **macOS:** Native `screencapture` command (no dependencies)
- **Windows/Linux:** PIL/Pillow required (`pip install Pillow`)

**Configuration:**
```bash
# Optional: customize screenshot directory in .env
SCREENSHOTS_DIR=screenshots  # Default: screenshots/
```

---

### MCP Tools (Desktop Automation) ✅ STABLE

**macOS-Automator-MCP** provides native macOS automation using AppleScript, JXA, and accessibility APIs:

**Migration Note:** This project previously used Computer-Control-MCP (PyAutoGUI-based), which was abandoned due to limitations in image processing and significant latency issues. macOS-Automator-MCP offers superior performance and native macOS integration.

Halfred can control your computer with built-in safety confirmations:

**`safe_action`** - Execute desktop automation actions with human-in-the-loop confirmation

**Supported Actions:**
- **Click/Double-click** - Click at specific screen coordinates
- **Type** - Type text into active window
- **Hotkeys** - Execute keyboard shortcuts (cmd+c, ctrl+v, etc.)
- **Window Control** - Focus and activate applications by name

**Safety Flow:**
1. 📸 Takes a screenshot for context
2. 🎯 Attempts a target preview; today this is a logged placeholder because visual highlighting is not implemented yet
3. ⏳ Requests confirmation via feedback-loop overlay or terminal fallback
4. ✅ Executes action only if approved

**Example Usage:**
```
You> Click the Safari icon in my dock
```
Halfred will:
- Identify the Safari icon location
- Take a screenshot for context
- Ask for confirmation via overlay or terminal prompt
- Click only if you approve

**Implementation:**

`automation_safety.py` is a Python module that provides the `safe_action` tool to the agent. This tool wraps raw automation capabilities with a mandatory safety confirmation flow, preventing the agent from executing desktop automation commands without user approval.

**What automation_safety.py does:**
- Provides a single `safe_action` tool that simplifies desktop automation
- Enforces human-in-the-loop confirmation for all state-changing actions
- Orchestrates the safety flow automatically (screenshot → preview/log target → confirm → execute)
- Routes tool calls to macos-automator-mcp using AppleScript/JXA execution
- Cannot be bypassed by the agent (enforced at the code level)

**Architecture:**
```
Agent calls: safe_action(action_type="click", x=100, y=200, description="Click Safari")
     ↓
automation_safety.py:
  1. Takes screenshot via macos-automator-mcp (AppleScript screencapture)
  2. Shows target region (highlight not yet implemented in macos-automator-mcp)
  3. Requests confirmation via feedback-loop-mcp
  4. If approved → Executes action via macos-automator-mcp (AppleScript/cliclick)
     If denied → Returns "Action cancelled by user"
```

**Why use a wrapper instead of raw MCP tools?**
- **Safety by default:** Agent cannot call click_screen/type_text directly
- **Simpler for agent:** One tool instead of coordinating multiple separate tools
- **Consistent pattern:** Matches pty_proxy_mcp design (risky commands require approval)
- **Reduces errors:** Less cognitive load for the agent means fewer mistakes

**Components:**
- **macos-automator-mcp:** Native macOS automation using AppleScript/JXA and accessibility APIs
- **feedback-loop-mcp:** Native macOS overlay for confirmation UI (optional)
- **automation_safety.py:** Safety wrapper that exposes only the `safe_action` tool
- **cliclick:** Command-line tool for precise mouse control (requires: `brew install cliclick`)

**Platform Support:**
- **macOS only:** macos-automator-mcp uses native macOS AppleScript and accessibility APIs

**Configuration:**
```bash
# Enable in .env
ENABLE_MACOS_AUTOMATOR_MCP=false  # Set to true to enable desktop automation
ENABLE_FEEDBACK_LOOP_MCP=false  # Set to true for visual confirmation overlays (macOS only)
AUTOMATION_REQUIRE_APPROVAL=true  # Safety: always confirm before actions
DEV_MODE=true  # Recommended for testing automation features
```

**Installation (for automation features):**
```bash
# Install cliclick (required for mouse control)
brew install cliclick

# Install the optional feedback-loop dependency if you want overlay confirmations
npm install

# Verify Node.js 16+ is available (package.json currently declares >=16.0.0)
node --version

# Before enabling ENABLE_MACOS_AUTOMATOR_MCP=true, update the macos-automator
# command in MCP_SERVERS.json to point to your local macos-automator-mcp/start.sh

# automation_safety.py currently invokes /opt/homebrew/bin/cliclick directly.
# If Homebrew installs cliclick elsewhere, update that path in automation_safety.py

# On macOS: Grant permissions in System Settings > Privacy & Security
# - Accessibility (for UI automation)
# - Automation (for controlling other applications)
```

**Developer Commands** (enable with `DEV_MODE=true`):
- `/screeninfo` - Display screen dimensions
- `/screenshot [full|active]` - Capture a debug screenshot (the current implementation always performs a full-screen capture)
- `/highlight x y w h` - Exercise the highlight path; the current implementation logs the requested region instead of drawing it
- `/confirm_test` - Test feedback loop UI
- `/demo_click` - Full safety demo

📚 **For detailed usage examples, see the desktop automation section above or try the developer commands.**

⚠️ **IMPORTANT: Always keep AUTOMATION_REQUIRE_APPROVAL=true for safety unless you have a specific automated workflow that requires it.**

## Setup

### Prerequisites

#### All Platforms
- **Python 3.8+** (Python 3.10+ recommended)
- **OpenAI API key** (with Realtime API access)
- **ElevenLabs API key** (for TTS)
- **Git** (with submodule support)

#### Platform-Specific Requirements

**macOS:**
- Audio works out of the box (Core Audio)
- Terminal access via bash (built-in)

**Windows:**
- PortAudio DLL (automatically installed with `sounddevice` package)
- Terminal access via cmd.exe (built-in)
- **Note:** Some Windows security software may flag microphone/screen access - grant permissions when prompted

**Linux:**
- Install PortAudio library:
  ```bash
  # Debian/Ubuntu
  sudo apt-get install libportaudio2

  # Fedora/RHEL
  sudo dnf install portaudio

  # Arch
  sudo pacman -S portaudio
  ```
- Terminal access via bash (built-in)

### Installation

#### 1. Clone the repository with submodules

```bash
# Clone with all submodules
git clone --recursive https://github.com/edwardandrew-a11y/Realtime_HALfred.git
cd Realtime_HALfred
```

If you already cloned without `--recursive`:
```bash
cd Realtime_HALfred
git submodule update --init --recursive
```

#### 2. Create and activate virtual environment

**macOS/Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**Windows (Command Prompt):**
```cmd
python -m venv .venv
.venv\Scripts\activate.bat
```

#### 3. Install main dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**Key dependencies installed:**
- `openai-agents>=0.6.0` - OpenAI Agents SDK with Realtime API support
- `elevenlabs>=1.0.0` - ElevenLabs TTS API
- `sounddevice>=0.4.6` - Cross-platform audio I/O
- `pynput>=1.7.6` - Keyboard monitoring for push-to-talk functionality
- `python-dotenv>=1.0.0` - Environment variable management
- `mcp>=1.0.0` - Model Context Protocol support

#### 4. Install ScreenMonitorMCP submodule

```bash
cd ScreenMonitorMCP
pip install -e .
cd ..
```

This installs the screen monitoring capabilities with dependencies:
- `fastapi`, `uvicorn` - Web framework
- `mss` - Screenshot capture
- `Pillow` - Image processing
- `openai` - Vision API client
- `psutil` - System monitoring
- `pydantic`, `structlog`, `aiosqlite` - Supporting libraries

### Configuration

1. **Create `.env` file:**
```bash
cp .env.example .env
```

2. **Add your API keys and personalization to `.env`:**
```env
OPENAI_API_KEY=your-openai-api-key-here
ELEVENLABS_API_KEY=your-elevenlabs-api-key-here
ELEVENLABS_VOICE_ID=2ajXGJNYBR0iNHpS4VZb  # Optional: defaults to Rob voice

# Personalize Halfred's knowledge about you
USER_NAME=Your Name
USER_CONTEXT=your occupation, interests, hobbies, etc.
```

3. **Review MCP server configuration:**

The checked-in `MCP_SERVERS.json` is enough for `screen-monitor`, `pty-proxy`, and the wrapped `feedback-loop` server once dependencies are installed. Its `macos-automator` entry points to a machine-specific absolute path, so update that command before you enable desktop automation.

```json
[
  {
    "name": "screen-monitor",
    "transport": "stdio",
    "params": {
      "command": "python",
      "args": ["-m", "screenmonitormcp_v2.mcp_main"],
      "env": {
        "OPENAI_API_KEY": "${OPENAI_API_KEY}",
        "OPENAI_MODEL": "gpt-4o"
      }
    }
  },
  {
    "name": "pty-proxy",
    "transport": "stdio",
    "params": {
      "command": "python",
      "args": ["pty_proxy_mcp.py"]
    },
    "client_session_timeout_seconds": 60
  }
]
```

**Notes:**
- Uses `python` command (works with activated virtual environment)
- Environment variables like `${OPENAI_API_KEY}` are automatically substituted from your `.env` file
- PTY terminal access is enabled by default. To disable it entirely, remove the `pty-proxy` entry from `MCP_SERVERS.json`
- `PTY_REQUIRE_APPROVAL=false` does not disable PTY; it only disables confirmation prompts for risky shell commands
- The checked-in file also includes optional `macos-automator` and `feedback-loop` entries; see `MCP_SERVERS.json.example` if you want a clean template

## Usage

1. **Start Halfred:**

**macOS/Linux:**
```bash
python main.py
```

**Windows:**
```cmd
python main.py
```

2. **Grant necessary permissions:**
   - **macOS:** Grant microphone and screen recording permissions when prompted
   - **Windows:** Grant microphone access when prompted. If Windows Defender flags the app, allow it through (it's because of audio/screen capture)
   - **Linux:** Ensure your user has access to audio devices (usually automatic)

3. **Interact with Halfred:**

### Commands
- **Type messages** - Send text messages directly
- **`/mic`** - Toggle continuous listening mode (hands-free)
- **`/ptt`** - Toggle push-to-talk mode
- **`/stop`** - Interrupt HALfred's speech immediately
- **`/mcp`** - List all available MCP tools and servers
- **`/retry`** - Retry the Realtime connection after a reconnect failure
- **`/quit` or `/exit`** - Exit the program

### Voice Interaction Modes

#### Continuous Listening Mode (`/mic`)
When continuous listening is enabled:
- Halfred automatically detects when you start and stop speaking (semantic VAD)
- Microphone automatically mutes while Halfred is speaking (prevents echo)
- Automatically resumes listening after Halfred finishes responding
- If the Realtime websocket is dormant, `/mic` wakes and reconnects it before resuming hands-free listening

#### Push-to-Talk Mode (`/ptt`)
When push-to-talk is enabled:
- Hold your configured `PTT_KEY` combo or key to record your voice
- Visual indicator shows when recording: `[ptt] >> RECORDING (keys held)`
- Release keys to send your message to Halfred
- Automatically interrupts Halfred's speech when you press the PTT keys
- Can be customized via `PTT_KEY` in `.env`; the shipped `.env.example` uses `cmd_alt_ctrl`, and single keys such as `space`, `ctrl`, `shift`, `alt`, or letters also work
- If the Realtime websocket is dormant, pressing PTT wakes it and buffers your first utterance during reconnect

**macOS Permissions Required:**
- System Settings → Privacy & Security → Accessibility
- Grant permission for your Terminal or IDE to monitor keyboard events

**Note:** By default, HALfred starts in continuous listening mode. Use `/ptt` to switch to push-to-talk, and `/mic` to switch back.

### Dormant Session Lifecycle

HALfred now keeps the app process alive even when the active Realtime websocket is closed for inactivity or proactive session rotation.

- After `DORMANT_TIMEOUT_MINUTES` of no user activity, HALfred closes the active Realtime session and enters a dormant state
- While dormant, the app, MCP servers, keyboard listener, microphone pipeline, and Supervisor agent stay loaded
- Pressing PTT or typing a message wakes HALfred and reconnects the Realtime session automatically
- HALfred also rotates the Realtime session before the API's 60-minute hard cap using `SESSION_MAX_MINUTES`
- If reconnect attempts fail, HALfred enters a recoverable failed state and waits for `/retry` or `/quit`

## Architecture

HALfred uses a **two-tier agent architecture**:

1. **Realtime Agent** - "Front desk" for low-latency conversation and escalation; its only tool is `escalate_to_supervisor`
2. **Supervisor Agent** - Handles screenshots, web search, code, Anki, terminal access, automation, and MCP tools

An optional **Metaprompt Agent** runs between sessions when `ENABLE_METAPROMPT_AGENT=true`. It reads recent logs, user feedback, prompt version history, and the feedback-derived constraint registry, then proposes prompt changes for explicit human approval. See [docs/METAPROMPT.md](docs/METAPROMPT.md).

```
┌─────────────────────────────────────────────────────────────┐
│                      Realtime HALfred                        │
└─────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
           ┌──────────────┐    ┌──────────────────┐
           │   OpenAI     │    │   Supervisor     │
           │  Realtime    │    │   (Responses)    │
           │  "Front Desk"│    │   Complex Tasks  │
           │  - Voice I/O │    │   - Web Search   │
           │  - Simple Q&A│    │   - Code Interp  │
           │  - Escalation│    │   - Image Gen    │
           └──────────────┘    │   - File Search  │
                    │          │   - Screenshots  │
                    │          │   - MCP Tools    │
                    │          │   - Automation   │
                    │          │   - Anki         │
                    │          └──────────────────┘
                    │                   │
        ┌───────────┼───────────┐       │
        ▼           ▼           ▼       ▼
┌────────────┐ ┌──────────┐ ┌──────────────────┐
│ ElevenLabs │ │  Audio   │ │   MCP Servers    │
│    TTS     │ │  Player  │ │ (screen, pty,    │
│            │ │          │ │  automator)      │
└────────────┘ └──────────┘ └──────────────────┘
        │           │
        └─────┬─────┘
              ▼
       ┌─────────────┐
       │ MicStreamer │
       │(sounddevice)│
       └─────────────┘
```

### Routing Logic

| User Request | Handled By | Reason |
|--------------|------------|--------|
| "Tell me a joke" | Realtime | Simple conversation |
| "What time is it right now?" | Supervisor | Authoritative exact current time is available via `local_time` |
| "What's on my screen?" | Supervisor | Requires screen tools |
| "Search for AI news" | Supervisor | Requires web_search |
| "Write Python code" | Supervisor | Requires code_interpreter |
| "Generate an image" | Supervisor | Requires image_generation |
| "Open Anki browser" | Supervisor | Uses `anki_agent` |
| "Run a terminal command" | Supervisor | Requires MCP tools |

See [docs/SUPERVISOR.md](docs/SUPERVISOR.md) for detailed architecture documentation.

## Agent Observability and Log Viewer

HALfred writes structured session logs to `logs/<session_id>.jsonl` while the app is running, plus a summary `logs/<session_id>.json` on shutdown. The logger now records the full multi-agent communication path with causal IDs so you can reconstruct what each agent saw, what it sent, and which response or tool call triggered the next step.

### What Gets Logged

- Realtime user turns: audio transcripts, committed user messages, and complete assistant text responses
- Realtime tool events: `tool_start` / `tool_end` from the front-desk agent
- Realtime ↔ Supervisor handoffs: `agent_call` / `agent_response`
- Supervisor LLM rounds: per-round `llm_call`, `llm_response`, and surfaced `reasoning_summary`
- Supervisor ↔ tool/subagent calls: native tool, MCP tool, and Anki subagent request/response events
- Anki subagent internals: LLM calls/responses and AnkiConnect dispatches
- Context summarization: the background `ContextManager` summary prompt and model response
- Metaprompt lifecycle: `user_feedback`, `metaprompt_proposal`, `metaprompt_decision`, `metaprompt_skip`, and `feedback_processed`

When the metaprompt feature is enabled, proposal/decision logs also capture prompt-version comparisons, constraint operations, and the IDs of any constraints that were actually updated. For the full metaprompt flow and event schema, see [docs/METAPROMPT.md](docs/METAPROMPT.md).

Each event includes correlation fields when available:

| Field | Meaning |
|-------|---------|
| `trace_id` | One top-level user turn across Realtime, Supervisor, subagents, and tools |
| `interaction_id` | One full Supervisor escalation cycle |
| `span_id` / `parent_span_id` | Parent/child event relationships for tree reconstruction |
| `round` | Supervisor LLM round number |
| `response_id` | OpenAI Responses API response ID for chained rounds |
| `tool_call_id` | Function-call ID tying a tool event to the LLM call that requested it |

### Viewing Logs

Use `log_viewer.py` to inspect a saved session or follow a live JSONL file.

**Recommended command for live debugging:**

```bash
python log_viewer.py logs/<session_ID>.jsonl --follow --level detail
```

Replace `<session_ID>` with the actual filename from the `logs/` directory (e.g. `session_1775208209_8e0d79f3.jsonl`).

**Command options:**

| Option | Values | What it does |
|--------|--------|--------------|
| *(no flag)* | — | Read the file once and exit |
| `--follow` | — | Tail the file and print new events as they arrive (like `tail -f`). Use this while HALfred is running. |
| `--level` | `summary` | User turns, agent handoffs, final assistant replies, and errors only |
| | `detail` | Everything in summary, plus LLM calls/responses and reasoning summaries. **Good default for debugging.** |
| | `full` | Everything in detail, plus tool dispatches, tool start/end events, and per-delta assistant streaming |
| `--show-ids` | — | Print trace/span/interaction IDs alongside each event for correlating entries |
| `--refresh-interval` | seconds (default `0.5`) | How often `--follow` polls for new log lines |

**Examples:**

```bash
# Follow a live session (recommended)
python log_viewer.py logs/<session_ID>.jsonl --follow --level detail

# Read a completed session at full verbosity
python log_viewer.py logs/<session_ID>.jsonl --level full

# Follow with correlation IDs visible
python log_viewer.py logs/<session_ID>.jsonl --follow --level detail --show-ids
```

### Payload Capture Controls

By default, long prompts/responses/tool outputs are capped in logs to keep files manageable. Set `LOG_FULL_PAYLOADS=true` when you need full prompt/response and tool payload capture for debugging. This can store sensitive data and full tool arguments/results verbatim, so only enable it intentionally. Set `LOG_VERBOSE_DELTAS=true` to log every assistant text delta in addition to the assembled `assistant_text_complete` event.

## Audio Configuration

- **Sample Rate:** 24 kHz
- **Channels:** Mono (1 channel)
- **Format:** PCM16 (16-bit signed integer)
- **Input:** sounddevice RawInputStream
- **Output:** sounddevice RawOutputStream + ElevenLabs streaming

## Personality

Halfred's personality is defined by the active Realtime prompt loaded through `prompt_store.py`, typically from `prompts/realtime_prompt.md` with `{user_name}` and `{user_context}` filled at startup. If prompt loading fails, HALfred falls back to a minimal hardcoded safety prompt. Key traits:
- Refers to himself as "Halfred," never as an AI or assistant
- Quick, clever, and darkly humorous
- Casual, skeptical, and sometimes sarcastic
- Honest and blunt - no corporate-safe disclaimers
- Helpful and creative, but with attitude
- Prefers short, concise answers
- Learns about you from `USER_NAME` and `USER_CONTEXT` environment variables

## Troubleshooting

### ScreenMonitorMCP directory is empty
If the ScreenMonitorMCP directory exists but is empty, you need to initialize git submodules:
```bash
git submodule update --init --recursive
```
This is a common issue if you cloned without the `--recursive` flag. After running this command, proceed with the installation:
```bash
cd ScreenMonitorMCP
pip install -e .
cd ..
```

### JSONRPC parsing errors from MCP servers

**Symptoms:** You see errors like:
```
Failed to parse JSONRPC message from server
pydantic_core._pydantic_core.ValidationError: Invalid JSON
```

**Causes:**
- **feedback-loop-mcp**: Fixed with `feedback-loop-wrapper.js` (automatically used in `MCP_SERVERS.json`)
- **macos-automator-mcp**: No known JSONRPC issues

**Status:**
- ✅ **feedback-loop-mcp errors are FIXED** - The wrapper script eliminates all JSONRPC violations
- ✅ **macos-automator-mcp is clean** - No protocol violations or spurious logging

**If you still see feedback-loop-mcp errors:**
1. Verify `MCP_SERVERS.json` uses the wrapper:
   ```json
   {
     "name": "feedback-loop",
     "params": {
       "command": "node",
       "args": ["feedback-loop-wrapper.js"]
     }
   }
   ```
2. Restart the HALfred application
3. Check that `node_modules/feedback-loop-mcp/server/mcp-server.js` exists

See `FIXES_CHEAT_SHEET.md` for detailed technical information about these fixes.

### No audio output
- Check system audio output settings
- Verify ElevenLabs API key is valid
- Check if the configured voice ID exists (the shipped `.env.example` uses the voice labeled Rob)

### Microphone not working
- Grant microphone permissions to Terminal/IDE
- Check system audio input settings
- Verify sounddevice can access your mic:
```bash
python -c "import sounddevice as sd; print(sd.query_devices())"
```

### Push-to-talk not working
- **macOS:** Grant Accessibility permission to your Terminal/IDE:
  - System Settings → Privacy & Security → Accessibility
  - Add Terminal (or your IDE) to the allowed list
- Verify pynput is installed: `pip install pynput`
- Check that PTT is enabled: type `/ptt` in the console
- Try a different `PTT_KEY` in `.env` if your current combo does not register reliably
- Check console for `[keyboard]` messages indicating key detection

### MCP tools not loading
- Verify ScreenMonitorMCP is properly installed: `cd ScreenMonitorMCP && pip install -e .`
- Check MCP_SERVERS.json path is correct
- Ensure OpenAI API key is set in environment

### Automation features not working
- Check that `ENABLE_MACOS_AUTOMATOR_MCP=true` in `.env`
- If you plan to use feedback-loop overlays, verify Node.js 16+ is installed: `node --version`
- Update the `macos-automator` command in `MCP_SERVERS.json` so it points to your local `macos-automator-mcp/start.sh`
- Install cliclick: `brew install cliclick`
- If `which cliclick` does not resolve to `/opt/homebrew/bin/cliclick`, update the hardcoded path in `automation_safety.py`
- Check system permissions: System Settings > Privacy & Security > Accessibility + Automation
- Test with DEV_MODE commands first: `/demo_click`, `/screeninfo`
- For issues, check MCP server logs in the terminal output

### High latency
- ElevenLabs uses `optimizeStreamingLatency: 3` (max optimization)
- Check network connection stability
- Verify `eleven_turbo_v2_5` model is being used

### Realtime session went dormant
- This is expected after `DORMANT_TIMEOUT_MINUTES` of inactivity
- Press PTT or type any message to wake the session
- If reconnect fails, use `/retry`
- To change the idle sleep window, set `DORMANT_TIMEOUT_MINUTES` in `.env`

### Realtime session reconnects during long runs
- This is expected near the Realtime API's 60-minute session limit
- HALfred proactively rotates the websocket using `SESSION_MAX_MINUTES`, so the full app does not need to restart
- Recent conversation context is lightly reseeded on reconnect to preserve continuity

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | Yes | - | OpenAI API key for Realtime API |
| `ELEVENLABS_API_KEY` | Yes | - | ElevenLabs API key for TTS |
| `ELEVENLABS_VOICE_ID` | No | `2ajXGJNYBR0iNHpS4VZb` | Voice ID for ElevenLabs (the shipped `.env.example` labels this voice as Rob) |
| `USER_NAME` | No | `"the user"` | Your name for personalized interactions |
| `USER_CONTEXT` | No | `""` | Your occupation, interests, hobbies (e.g., "a med student who likes D&D") |
| `PTT_ENABLED` | No | `false` | Enable push-to-talk mode on startup |
| `PTT_KEY` | No | See `.env.example` | Push-to-talk key or modifier combo. The template uses `cmd_alt_ctrl`; if omitted entirely the runtime fallback is `cmd_alt` |
| `PTT_INTERRUPTS_SPEECH` | No | `true` | Whether PTT activation interrupts HALfred's speech |
| `DORMANT_TIMEOUT_MINUTES` | No | `30` | Minutes of inactivity before the Realtime websocket sleeps |
| `SESSION_MAX_MINUTES` | No | `55` | Minutes before HALfred proactively rotates the Realtime session |
| `MCP_SERVERS_JSON_FILE` | No | `MCP_SERVERS.json` | Path to MCP servers config file |
| `MCP_CLIENT_TIMEOUT_SECONDS` | No | `30` | Timeout for MCP tool calls |
| `MCP_DEMO_FILESYSTEM_DIR` | No | - | Optional demo filesystem MCP server |
| `PTY_REQUIRE_APPROVAL` | No | `true` | Require user confirmation for risky shell commands |
| `ENABLE_MACOS_AUTOMATOR_MCP` | No | `false` | Enable desktop automation features via macos-automator-mcp |
| `ENABLE_FEEDBACK_LOOP_MCP` | No | `false` | Enable feedback loop confirmation UI (macOS only) |
| `AUTOMATION_REQUIRE_APPROVAL` | No | `true` | Require confirmation for state-changing actions |
| `PREFERRED_DISPLAY_INDEX` | No | `0` | For dual monitors: which display to use (0=primary) |
| `SCREENSHOTS_DIR` | No | `screenshots` | Directory used by `screencapture` and debug screenshot helpers |
| `OPENAI_AGENTS_DISABLE_TRACING` | No | `1` in `.env.example` | Disable OpenAI Agents SDK telemetry if you want local-only tracing behavior |
| `DEV_MODE` | No | `false` | Enable developer debug commands |
| `SUPERVISOR_MODEL` | No | `gpt-4.1` | Model for Supervisor agent (Responses API) |
| `SUPERVISOR_VECTOR_STORE_ID` | No | - | Vector store ID for file_search RAG capability |
| `LOG_FULL_PAYLOADS` | No | `false` | Store uncapped LLM/tool payloads in logs. May include sensitive tool args/results verbatim |
| `LOG_VERBOSE_DELTAS` | No | `false` | Also log each assistant streaming delta as `assistant_text_delta` events |
| `ENABLE_METAPROMPT_AGENT` | No | `false` | Enable the dormancy-time metaprompt agent that proposes prompt improvements for approval |
| `METAPROMPT_MODEL` | No | `gpt-4.1` | Model used by the metaprompt agent |
| `PROMPT_HMAC_KEY` | No | unset | Optional HMAC key for prompt file integrity checking in `prompt_store.py` |

## Project Structure

Key files and directories:

```
Realtime_HALfred/
├── main.py                     # Main application entry point (Realtime agent)
├── supervisor.py               # Supervisor agent (Responses API for complex tasks)
├── metaprompt_agent.py         # Dormancy-time prompt optimization agent
├── prompt_store.py             # Versioned prompt loading, integrity checks, prompt deployment
├── constraint_registry.py      # Feedback-derived prompt constraint registry
├── anki_agent.py               # Anki subagent used by the Supervisor
├── anki_connect.py             # Thin AnkiConnect client
├── session_logger.py           # Session event logger
├── log_viewer.py               # CLI for rendering JSONL logs as a causal tree
├── mcp_schema_fix.py           # Patches MCP tool schemas for Realtime API compatibility
├── native_screenshot.py        # Native screenshot tool exposed to the Supervisor
├── automation_safety.py        # Desktop automation safety wrapper
├── pty_proxy_mcp.py            # PTY MCP proxy server (cross-platform)
├── pty_command_safety.py       # PTY command safety module
├── MCP_SERVERS.json            # Checked-in MCP config; macos-automator entry is machine-specific
├── MCP_SERVERS.json.example    # Example MCP configuration
├── .env.example                # Example environment file template
├── README.md                   # This file
├── FIXES_CHEAT_SHEET.md        # Notes on MCP and automation fixes
├── prompt_versions.json        # Auto-generated prompt version ledger
├── package.json                # Node.js dependencies (feedback-loop-mcp only)
├── requirements.txt            # Python dependencies with platform notes
├── config.yaml                 # PTY MCP configuration
├── docs/
│   ├── METAPROMPT.md           # Metaprompt agent architecture and operations
│   ├── SUPERVISOR.md           # Supervisor agent architecture documentation
│   ├── AUTOMATION.md           # Automation notes
│   ├── AUTOMATION_IMPLEMENTATION.md  # Technical implementation details
│   └── KNOWN_ISSUES.md         # Known issues and deferred fixes
├── prompts/                    # Versioned prompt files, contract, and constraint registry
├── ScreenMonitorMCP/           # Screen monitoring MCP server (git submodule)
├── logs/                       # Session logs written by session_logger.py
├── screenshots/                # Saved screenshots from screencapture and debug helpers
└── .venv/                      # Local virtual environment (created during setup)
```

## Credits

- Built with [@openai/agents](https://github.com/openai/openai-agents-python) Python SDK
- TTS powered by [ElevenLabs](https://elevenlabs.io/)
- Screen monitoring via [ScreenMonitorMCP](https://github.com/inkbytefo/ScreenMonitorMCP)
- Audio I/O via [sounddevice](https://python-sounddevice.readthedocs.io/)
