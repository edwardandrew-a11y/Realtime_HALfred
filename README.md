# Realtime HALfred

A Python-based realtime voice assistant powered by OpenAI's Realtime API and ElevenLabs TTS. HALfred is a sardonic, sharp-tongued AI companion with personality, capable of natural voice conversations and equipped with screen monitoring capabilities through MCP integration.

## Overview

Realtime HALfred uses:
- **OpenAI Realtime API** (`gpt-realtime`) for low-latency voice interactions with native STT
- **ElevenLabs** for high-quality, natural text-to-speech output
- **ScreenMonitorMCP** for AI vision and screen analysis capabilities
- **MCP (Model Context Protocol)** for extensible tool integration
- **Semantic VAD** for intelligent turn detection
- **Whisper-1** for optional input audio transcription (debugging)

## Features

- 🎙️ **Continuous Voice Interaction** - Toggle hands-free listening with `/mic` command
- 🗣️ **Natural TTS** - ElevenLabs streaming audio for low-latency, natural speech
- 🎭 **Personality-Driven** - Halfred has a distinct personality: sardonic, helpful, and unfiltered
- 👁️ **Vision Capabilities** - Screen capture and AI-powered visual analysis through MCP
- 🔧 **Extensible Tools** - MCP integration allows adding new capabilities easily
- 🎧 **Half-Duplex Audio** - Automatic mic muting during playback to prevent echo

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

## Setup

### Prerequisites
- Python 3.8+
- macOS (for audio I/O with sounddevice)
- OpenAI API key
- ElevenLabs API key

### Installation

1. **Clone the repository:**
```bash
git clone --recursive <your-repo-url>
cd Realtime_HALfred
```

2. **Create and activate virtual environment:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

3. **Install Python dependencies:**
```bash
pip install -r requirements.txt  # or install packages from main.py imports
```

Key dependencies:
- `openai-agents` (with realtime support)
- `elevenlabs`
- `sounddevice`
- `python-dotenv`

4. **Set up ScreenMonitorMCP submodule:**
```bash
cd ScreenMonitorMCP
pip install -e .
cd ..
```

### Configuration

1. **Create `.env` file:**
```bash
cp .env.example .env
```

2. **Add your API keys and personalization to `.env`:**
```env
OPENAI_API_KEY=your-openai-api-key-here
ELEVENLABS_API_KEY=your-elevenlabs-api-key-here
ELEVENLABS_VOICE_ID=2ajXGJNYBR0iNHpS4VZb  # Optional: defaults to Rachel voice

# Personalize Halfred's knowledge about you
USER_NAME=Your Name
USER_CONTEXT=your occupation, interests, hobbies, etc.
```

3. **Configure MCP servers in `MCP_SERVERS.json`:**
```json
[
  {
    "name": "screen-monitor",
    "transport": "stdio",
    "params": {
      "command": "/Users/YOUR_USERNAME/PATH_TO/ScreenMonitorMCP/.venv/bin/python",
      "args": ["-m", "screenmonitormcp_v2.mcp_main"],
      "env": {
        "OPENAI_API_KEY": "${OPENAI_API_KEY}",
        "OPENAI_MODEL": "gpt-4o"
      }
    }
  }
]
```

## Usage

1. **Start Halfred:**
```bash
python main.py
```

2. **Grant microphone permissions** when macOS prompts.

3. **Interact with Halfred:**

### Commands
- **Type messages** - Send text messages directly
- **`/mic`** - Toggle continuous listening mode (hands-free)
- **`/mcp`** - List all available MCP tools and servers
- **`/quit` or `/exit`** - Exit the program

### Continuous Listening Mode
When continuous listening is enabled (`/mic`):
- Halfred automatically detects when you start and stop speaking (semantic VAD)
- Microphone automatically mutes while Halfred is speaking (prevents echo)
- Automatically resumes listening after Halfred finishes responding

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

Halfred's personality is defined in `main.py:639-657`. Key traits:
- Refers to himself as "Halfred," never as an AI or assistant
- Quick, clever, and darkly humorous
- Casual, skeptical, and sometimes sarcastic
- Honest and blunt - no corporate-safe disclaimers
- Helpful and creative, but with attitude
- Prefers short, concise answers
- Learns about you from `USER_NAME` and `USER_CONTEXT` environment variables

## Troubleshooting

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

### MCP tools not loading
- Verify ScreenMonitorMCP is properly installed: `cd ScreenMonitorMCP && pip install -e .`
- Check MCP_SERVERS.json path is correct
- Ensure OpenAI API key is set in environment

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
| `MCP_SERVERS_JSON_FILE` | No | `MCP_SERVERS.json` | Path to MCP servers config file |
| `MCP_CLIENT_TIMEOUT_SECONDS` | No | `30` | Timeout for MCP tool calls |
| `MCP_DEMO_FILESYSTEM_DIR` | No | - | Optional demo filesystem MCP server |

## Project Structure

```
Realtime_HALfred/
├── main.py                 # Main application entry point
├── MCP_SERVERS.json        # MCP server configuration
├── .env                    # Environment variables (API keys)
├── .env.example            # Example environment file
├── .gitignore              # Git ignore rules
├── .gitmodules             # Git submodule configuration
├── README.md               # This file
├── ScreenMonitorMCP/       # Screen monitoring MCP server (submodule)
└── .venv/                  # Python virtual environment
```

## License

See LICENSE file for details.

## Credits

- Built with [@openai/agents](https://github.com/openai/openai-agents-python) Python SDK
- TTS powered by [ElevenLabs](https://elevenlabs.io/)
- Screen monitoring via [ScreenMonitorMCP](https://github.com/inkbytefo/ScreenMonitorMCP)
- Audio I/O via [sounddevice](https://python-sounddevice.readthedocs.io/)
