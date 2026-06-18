# TikTok Live Bridge

This is a lightweight Node.js script that connects to a TikTok Live stream using the `tiktok-live-connector` library.
It listens to WebSockets and outputs chat, gift, like, and follow events as JSON strings to `stdout`.

The Python backend (`src.ingestion.chat_collector.ChatCollector`) spawns this script as a subprocess and reads the JSON lines.

## Usage

1. Install Node.js (>= 18)
2. Run `npm install` inside this directory (`tools/tiktok_bridge`)
3. Test locally: `node index.js some_tiktok_username`
