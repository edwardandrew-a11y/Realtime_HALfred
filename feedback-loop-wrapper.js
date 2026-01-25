#!/usr/bin/env node

/**
 * Wrapper for feedback-loop-mcp that fixes multi-JSON concatenation bug.
 *
 * Problem: feedback-loop-mcp writes multiple JSON objects to stdout without
 * newline separators, violating JSONRPC protocol which requires line-delimited messages.
 *
 * Solution: This wrapper intercepts stdout, detects JSON object boundaries,
 * and ensures proper newline separation between messages.
 */

const { spawn } = require('child_process');
const path = require('path');

// Find the actual mcp-server.js script (not the bin wrapper)
// The bin script uses stdio: 'inherit' which bypasses our interception
const serverPath = path.join(__dirname, 'node_modules', 'feedback-loop-mcp', 'server', 'mcp-server.js');

// Spawn the MCP server directly with piped stdout
const child = spawn('node', [serverPath, ...process.argv.slice(2)], {
  stdio: ['inherit', 'pipe', 'inherit'], // stdin=inherit, stdout=pipe, stderr=inherit
  env: process.env
});

// Buffer to accumulate partial data
let buffer = '';
let braceDepth = 0;
let inString = false;
let escapeNext = false;

// Process stdout character by character to detect JSON boundaries
child.stdout.on('data', (chunk) => {
  const text = chunk.toString();

  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    buffer += char;

    // Track string state to ignore braces inside strings
    if (escapeNext) {
      escapeNext = false;
      continue;
    }

    if (char === '\\') {
      escapeNext = true;
      continue;
    }

    if (char === '"') {
      inString = !inString;
      continue;
    }

    // Only count braces outside of strings
    if (!inString) {
      if (char === '{') {
        braceDepth++;
      } else if (char === '}') {
        braceDepth--;

        // When we close a complete JSON object (braceDepth returns to 0)
        if (braceDepth === 0 && buffer.trim().length > 0) {
          const trimmed = buffer.trim();

          // Only output valid JSON (starts with '{'), filter out debug logs
          if (trimmed.startsWith('{')) {
            process.stdout.write(trimmed + '\n');
          } else {
            // Debug logs go to stderr so they don't pollute JSONRPC stream
            console.error('[feedback-loop-wrapper] Filtered non-JSON output:', trimmed);
          }

          buffer = '';
        }
      } else if (char === '\n' && braceDepth === 0) {
        // Handle newline-separated non-JSON debug messages
        const trimmed = buffer.trim();
        if (trimmed.length > 0 && !trimmed.startsWith('{')) {
          console.error('[feedback-loop-wrapper] Filtered debug log:', trimmed);
          buffer = '';
        }
      }
    }
  }
});

// Forward exit code
child.on('exit', (code, signal) => {
  // Flush any remaining buffer
  if (buffer.trim().length > 0) {
    process.stdout.write(buffer.trim() + '\n');
  }
  process.exit(code || 0);
});

// Handle errors
child.on('error', (err) => {
  console.error('[feedback-loop-wrapper] Failed to start feedback-loop-mcp:', err);
  process.exit(1);
});
