# slice-worker/config.go · [[slice-worker-node]]

Worker configuration file defining node identity, Redis connection, task routing streams, and capability detection for the slice worker.

- Config · struct · L14-L39 — Data holder for worker runtime settings including node identity, Redis, task routing streams, retry policy, and resource limits.
- DefaultNodeID · function · L46-L62 — Generates a uniform node ID (slice-worker-<hostname>) by sanitizing the hostname to alphanumeric chars, truncating to 12, and lowercasing.
- DefaultConfig · function · L65-L82 — Returns a Config populated with sensible default values for a standalone worker.
- LoadConfig · function · L85-L109 — Loads worker config from a JSON file, falling back to defaults on read failure and enforcing NodeID and CPUPercent constraints.
- ClampCPUPercent · function · L112-L120 — Clamps a CPU allocation percentage into the valid 1-100 range for dynamic adjustments.
- HeartbeatTTL · method · L123-L128 — Returns the node heartbeat hash TTL, defaulting to 3x the heartbeat interval when not explicitly configured.
- EffectiveConsumeStreams · method · L141-L146 — Returns the configured consume streams, falling back to the default high/normal/low streams when none are set.
- GetOS · function · L149-L151 — Trivial accessor returning the runtime operating system name.
- GetArch · function · L154-L156 — Trivial accessor returning the runtime CPU architecture.
- GetFFmpegVersion · function · L159-L170 — Runs ffmpeg -version and returns the first output line as the version string, or 'unknown' on failure.
- GetEncoderCapabilities · function · L191-L209 — Detects which whitelisted hardware encoders the local ffmpeg supports by matching encoder names in ffmpeg -encoders output.
- GetIP · function · L216-L254 — Returns the node's IP by preferring a private IPv4 address, falling back to any non-loopback IPv4, without relying on external commands.
- isPrivateIPv4 · function · L257-L259 — Trivial predicate checking whether an IP is private or link-local unicast.
