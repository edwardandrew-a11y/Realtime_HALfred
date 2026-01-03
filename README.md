# Realtime HALfred

A Python-based realtime voice assistant powered by OpenAI's Realtime API and ElevenLabs TTS. HALfred is a sardonic, sharp-tongued AI companion with personality, capable of natural voice conversations and equipped with screen monitoring capabilities through MCP integration.

> **Recent Updates:** Tool schemas have been improved with proper type enforcement, enum constraints, and conditional validation. See [TOOLS.md](TOOLS.md) for complete documentation.

## Overview

Realtime HALfred uses:
- **OpenAI Realtime API** (`gpt-realtime`) for low-latency voice interactions with native STT
- **ElevenLabs** for high-quality, natural text-to-speech output
- **ScreenMonitorMCP** for AI vision and screen analysis capabilities
- **PTY Terminal Access** for safe shell command execution with user confirmation
- **MCP (Model Context Protocol)** for extensible tool integration
- **Semantic VAD** for intelligent turn detection
- **Whisper-1** for optional input audio transcription (debugging)

## Features

- 🎙️ **Continuous Voice Interaction** - Toggle hands-free listening with `/mic` command
- 🎤 **Push-to-Talk Mode** - Hold Command+Alt (or custom keys) to speak, release to send
- 🛑 **Speech Interruption** - Interrupt HALfred mid-response with `/stop` or PTT activation
- 🗣️ **Natural TTS** - ElevenLabs streaming audio for low-latency, natural speech
- 🎭 **Personality-Driven** - Halfred has a distinct personality: sardonic, helpful, and unfiltered
- 👁️ **Vision Capabilities** - Screen capture and AI-powered visual analysis through MCP
- 💻 **Terminal Access** - Safe shell command execution with command-level safety controls
- 🔧 **Extensible Tools** - MCP integration allows adding new capabilities easily
- 🎧 **Half-Duplex Audio** - Automatic mic muting during playback to prevent echo

## ⚠️ Important Notes

### Core Features (Stable)
The following features have been extensively tested and are production-ready:
- ✅ Voice interaction (OpenAI Realtime API + ElevenLabs TTS)
- ✅ Screen monitoring (ScreenMonitorMCP)
- ✅ PTY terminal access (pty-proxy-mcp)

### Stable Desktop Automation
The following desktop automation feature is now stable:
- ✅ **Desktop Automation (computer-control-mcp)** - Cross-platform PyAutoGUI-based automation via uvx

### Experimental Features (Use with Caution)
The following features are **experimental** and have not been fully tested:
- ⚠️ **Feedback Loop UI (feedback-loop-mcp)** - Not fully tested across all macOS versions

**Recommendations:**
- Test automation features in a safe environment first
- Use `DEV_MODE=true` and test commands (`/demo_click`, `/screeninfo`) before real usage
- Keep `AUTOMATION_REQUIRE_APPROVAL=true` to maintain safety
- Report issues to the project's GitHub issues page

## Available Tools

### Built-in Tools
- **`local_time`** - Returns the current local time (useful for sanity checks and time-aware responses)

### MCP Tools (ScreenMonitorMCP)
Halfred has access to the following visual and system monitoring tools:

1. **`capture_screen`** - Take screenshots of any monitor
2. **`analyze_screen`** - AI-powered screen content analysis and interpretation
3. **`analyze_image`** - Analyze any image file with AI vision capabilities
4. **`create_stream`** - Start live screen streaming for continuous monitoring
5. **`get_performance_metrics`** - System health monitoring and performance metrics

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
- **Risky commands** (mkdir, rm, chmod, network ops) require user confirmation
- **Dangerous commands** (rm -rf, sudo, dd) show strong warnings before execution
- Command parsing detects dangerous patterns (pipes to shell, output redirection, etc.)

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

### Native Screenshot Tool

**`take_screenshot`** - Fast, native OS screenshot capture with Realtime API integration

HALfred can see your screen using a native screenshot tool that:
- Captures screenshots using OS-native APIs (macOS `screencapture`, Windows/Linux PIL)
- Saves images to `screenshots/` directory with timestamp filenames
- Returns only metadata (path, dimensions) - no base64 in tool output
- Automatically sends images to Realtime API as proper visual inputs
- Works seamlessly across all platforms

**Two-Phase Screenshot Flow:**
1. **Tool Phase:** `take_screenshot` captures screen → saves to disk → returns metadata JSON
2. **Upload Phase:** Handler reads image file → sends to Realtime as `input_image` message

**Why this approach?**
- ✅ Avoids string size limits (tool output stays small)
- ✅ Efficient token usage (image sent as native multimodal input)
- ✅ Fast native capture (no dependencies on macOS)
- ✅ Agent receives actual image pixels, not text description

**Example Usage:**
```
You> What's on my screen?
HALfred> Let me take a look. [calls take_screenshot, receives image, describes what's visible]
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

**Computer-Control-MCP** provides cross-platform desktop automation capabilities:

Halfred can control your computer with built-in safety confirmations:

**`safe_action`** - Execute desktop automation actions with human-in-the-loop confirmation

**Supported Actions:**
- **Click/Double-click** - Click at specific screen coordinates
- **Type** - Type text into active window
- **Hotkeys** - Execute keyboard shortcuts (cmd+c, ctrl+v, etc.)
- **Window Control** - Focus and manage application windows
- **Screen Info** - Query screen dimensions and window positions (read-only)

**Safety Flow:**
1. 📸 Takes a screenshot for context
2. 🎯 Highlights the target region on screen
3. ⏳ Requests confirmation via native overlay UI
4. ✅ Executes action only if approved

**Example Usage:**
```
You> Click the Safari icon in my dock
```
Halfred will:
- Identify the Safari icon location
- Show you a highlighted screenshot
- Ask for confirmation via overlay
- Click only if you approve

**Implementation:**

`automation_safety.py` is a Python module that provides the `safe_action` tool to the agent. This tool wraps raw automation capabilities with a mandatory safety confirmation flow, preventing the agent from executing desktop automation commands without user approval.

**What automation_safety.py does:**
- Provides a single `safe_action` tool that simplifies desktop automation
- Enforces human-in-the-loop confirmation for all state-changing actions
- Orchestrates the 4-step safety flow automatically (screenshot → highlight → confirm → execute)
- Routes tool calls to computer-control-mcp or PyAutoGUI fallback
- Cannot be bypassed by the agent (enforced at the code level)

**Architecture:**
```
Agent calls: safe_action(action_type="click", x=100, y=200, description="Click Safari")
     ↓
automation_safety.py:
  1. Takes screenshot via computer-control-mcp
  2. Shows target region (highlight not supported in computer-control-mcp)
  3. Requests confirmation via feedback-loop-mcp
  4. If approved → Executes click_screen via computer-control-mcp
     If denied → Returns "Action cancelled by user"
```

**Why use a wrapper instead of raw MCP tools?**
- **Safety by default:** Agent cannot call click_screen/type_text directly
- **Simpler for agent:** One tool instead of coordinating multiple separate tools
- **Consistent pattern:** Matches pty_proxy_mcp design (risky commands require approval)
- **Reduces errors:** Less cognitive load for the agent means fewer mistakes

**Components:**
- **computer-control-mcp:** PyAutoGUI-based automation (mouse, keyboard, OCR, screenshots)
- **feedback-loop-mcp:** Native macOS overlay for confirmation UI (optional)
- **automation_safety.py:** Safety wrapper that exposes only the `safe_action` tool
- **PyAutoGUI:** Direct fallback when computer-control-mcp is unavailable

**Platform Support:**
- **All platforms:** computer-control-mcp works on macOS, Windows, and Linux via PyAutoGUI

**Configuration:**
```bash
# Enable in .env
ENABLE_COMPUTER_CONTROL_MCP=false  # Set to true to enable desktop automation
ENABLE_FEEDBACK_LOOP_MCP=false  # Set to true for visual confirmation overlays (macOS only)
AUTOMATION_REQUIRE_APPROVAL=true  # Safety: always confirm before actions
DEV_MODE=true  # Recommended for testing automation features
```

**Installation (for automation features):**
```bash
# Install UV (required to run uvx)
pip install uv

# computer-control-mcp will be automatically installed when first run via uvx
# The first run will download dependencies (~70MB) which may take a moment

# On macOS/Linux: Grant permissions in System Settings
# - Accessibility (for mouse/keyboard control)
# - Screen Recording (for screenshots)

# On Windows: Grant permissions when prompted
```

**Developer Commands** (enable with `DEV_MODE=true`):
- `/screeninfo` - Display screen dimensions
- `/screenshot [full|active]` - Capture screen
- `/highlight x y w h` - Test highlight overlay
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

3. **Configure MCP servers (should work as-is):**

The `MCP_SERVERS.json` file is already configured with relative paths and should work out of the box after installation:

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
- PTY terminal access is enabled by default. To disable it, remove the `pty-proxy` entry or set `PTY_REQUIRE_APPROVAL=false` in `.env`
- See `MCP_SERVERS.json.example` for additional configuration options

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
- **`/quit` or `/exit`** - Exit the program

### Voice Interaction Modes

#### Continuous Listening Mode (`/mic`)
When continuous listening is enabled:
- Halfred automatically detects when you start and stop speaking (semantic VAD)
- Microphone automatically mutes while Halfred is speaking (prevents echo)
- Automatically resumes listening after Halfred finishes responding

#### Push-to-Talk Mode (`/ptt`)
When push-to-talk is enabled:
- Hold **Command+Alt** keys (macOS) to record your voice
- Visual indicator shows when recording: `[ptt] >> RECORDING (keys held)`
- Release keys to send your message to Halfred
- Automatically interrupts Halfred's speech when you press the PTT keys
- Can be customized via `PTT_KEY` in `.env` (options: `cmd_alt`, `space`, `ctrl`, `shift`, etc.)

**macOS Permissions Required:**
- System Settings → Privacy & Security → Accessibility
- Grant permission for your Terminal or IDE to monitor keyboard events

**Note:** By default, HALfred starts in continuous listening mode. Use `/ptt` to switch to push-to-talk, and `/mic` to switch back.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Realtime HALfred                        │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌──────────────┐    ┌──────────────────┐    ┌────────────┐
│   OpenAI     │    │   ElevenLabs     │    │    MCP     │
│  Realtime    │    │      TTS         │    │  Servers   │
│  (STT+LLM)   │    │   (Streaming)    │    │            │
└──────────────┘    └──────────────────┘    └────────────┘
        │                     │                     │
        ▼                     ▼                     ▼
┌──────────────┐    ┌──────────────────┐    ┌────────────┐
│   Optional   │    │   AudioPlayer    │    │  Screen    │
│   Whisper    │    │  (sounddevice)   │    │  Monitor   │
│  Transcript  │    │                  │    │            │
└──────────────┘    └──────────────────┘    └────────────┘
        │                     │
        └──────────┬──────────┘
                   ▼
            ┌─────────────┐
            │ MicStreamer │
            │(sounddevice)│
            └─────────────┘
```

## Audio Configuration

- **Sample Rate:** 24 kHz
- **Channels:** Mono (1 channel)
- **Format:** PCM16 (16-bit signed integer)
- **Input:** sounddevice RawInputStream
- **Output:** sounddevice RawOutputStream + ElevenLabs streaming

## Personality

Halfred's personality is defined in `main.py:807-830`. Key traits:
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

### No audio output
- Check system audio output settings
- Verify ElevenLabs API key is valid
- Check if voice ID exists (default: Rachel)

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
- Try a different key combination in `.env` if `cmd_alt` doesn't work
- Check console for `[keyboard]` messages indicating key detection

### MCP tools not loading
- Verify ScreenMonitorMCP is properly installed: `cd ScreenMonitorMCP && pip install -e .`
- Check MCP_SERVERS.json path is correct
- Ensure OpenAI API key is set in environment

### Automation features not working
- Check that `ENABLE_COMPUTER_CONTROL_MCP=true` in `.env`
- Verify UV is installed: `pip install uv`
- Run `uvx computer-control-mcp@latest --help` to test installation
- Check system permissions: Accessibility + Screen Recording (macOS/Linux)
- Test with DEV_MODE commands first: `/demo_click`, `/screeninfo`
- For issues, check MCP server logs or try direct PyAutoGUI: `pip install pyautogui`

### High latency
- ElevenLabs uses `optimizeStreamingLatency: 3` (max optimization)
- Check network connection stability
- Verify `eleven_turbo_v2_5` model is being used

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | Yes | - | OpenAI API key for Realtime API |
| `ELEVENLABS_API_KEY` | Yes | - | ElevenLabs API key for TTS |
| `ELEVENLABS_VOICE_ID` | No | `2ajXGJNYBR0iNHpS4VZb` | Voice ID for ElevenLabs (default: Rachel) |
| `USER_NAME` | No | `"the user"` | Your name for personalized interactions |
| `USER_CONTEXT` | No | `""` | Your occupation, interests, hobbies (e.g., "a med student who likes D&D") |
| `PTT_ENABLED` | No | `false` | Enable push-to-talk mode on startup |
| `PTT_KEY` | No | `cmd_alt` | Keys for push-to-talk (`cmd_alt`, `space`, `ctrl`, `shift`, `alt`, or any letter) |
| `PTT_INTERRUPTS_SPEECH` | No | `true` | Whether PTT activation interrupts HALfred's speech |
| `MCP_SERVERS_JSON_FILE` | No | `MCP_SERVERS.json` | Path to MCP servers config file |
| `MCP_CLIENT_TIMEOUT_SECONDS` | No | `30` | Timeout for MCP tool calls |
| `MCP_DEMO_FILESYSTEM_DIR` | No | - | Optional demo filesystem MCP server |
| `PTY_REQUIRE_APPROVAL` | No | `true` | Require user confirmation for risky shell commands |
| `PTY_SAFE_COMMANDS` | No | See `.env.example` | Comma-separated list of safe commands |
| `FILESYSTEM_REQUIRE_APPROVAL` | No | `true` | Require user confirmation for risky file operations |
| `ENABLE_COMPUTER_CONTROL_MCP` | No | `false` | Enable desktop automation features via computer-control-mcp |
| `ENABLE_FEEDBACK_LOOP_MCP` | No | `false` | Enable feedback loop confirmation UI (macOS only) |
| `COMPUTER_CONTROL_MCP_TIMEOUT` | No | `600` | Timeout for automation tool calls (seconds) |
| `AUTOMATION_REQUIRE_APPROVAL` | No | `true` | Require confirmation for state-changing actions |
| `PREFERRED_DISPLAY_INDEX` | No | `0` | For dual monitors: which display to use (0=primary) |
| `DEV_MODE` | No | `false` | Enable developer debug commands |

## Project Structure

```
Realtime_HALfred/
├── main.py                     # Main application entry point
├── MCP_SERVERS.json            # MCP server configuration (uses relative paths)
├── MCP_SERVERS.json.example    # Example MCP configuration
├── .env                        # Environment variables (API keys) - create from .env.example
├── .env.example                # Example environment file template
├── pty_command_safety.py       # PTY command safety module
├── pty_proxy_mcp.py            # PTY MCP proxy server (cross-platform)
├── test_pty_safety.py          # PTY safety test suite
├── automation_safety.py        # Desktop automation safety wrapper
├── test_automation_mcp.py      # Automation MCP smoke tests
├── package.json                # Node.js dependencies (feedback-loop-mcp only)
├── config.yaml                 # PTY MCP configuration
├── requirements.txt            # Python dependencies with platform notes
├── .gitignore                  # Git ignore rules
├── .gitmodules                 # Git submodule configuration
├── README.md                   # This file
├── docs/
│   ├── AUTOMATION.md           # Desktop automation user guide
│   └── AUTOMATION_IMPLEMENTATION.md  # Technical implementation details
├── ScreenMonitorMCP/           # Screen monitoring MCP server (git submodule)
├── data/                       # Data directory (logs, SQLite memory DB)
├── node_modules/               # Node.js packages (feedback-loop-mcp)
└── .venv/                      # Python virtual environment (not in git)
```

## License

See LICENSE file for details.

## Credits

- Built with [@openai/agents](https://github.com/openai/openai-agents-python) Python SDK
- TTS powered by [ElevenLabs](https://elevenlabs.io/)
- Screen monitoring via [ScreenMonitorMCP](https://github.com/inkbytefo/ScreenMonitorMCP)
- Audio I/O via [sounddevice](https://python-sounddevice.readthedocs.io/)
