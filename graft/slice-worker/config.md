# slice-worker/config.go · [[slice-worker-node]]

Worker configuration file defining node identity, Redis connection, task routing streams, and capability detection for the slice worker.

- Config · struct · L14-L43 — Data holder for worker runtime settings including node identity, Redis, task routing streams, retry policy, and resource limits.
- DefaultNodeID · function · L50-L66 — Generates a uniform node ID (slice-worker-<hostname>) by sanitizing the hostname to alphanumeric chars, truncating to 12, and lowercasing.
- DefaultConfig · function · L69-L87 — Returns a Config populated with sensible default values for a standalone worker.
- LoadConfig · function · L90-L114 — Loads worker config from a JSON file, falling back to defaults on read failure and enforcing NodeID and CPUPercent constraints.
- ClampCPUPercent · function · L117-L125 — Clamps a CPU allocation percentage into the valid 1-100 range for dynamic adjustments.
- HeartbeatTTL · method · L128-L133 — Returns the node heartbeat hash TTL, defaulting to 3x the heartbeat interval when not explicitly configured.
- EffectiveConsumeStreams · method · L146-L151 — Returns the configured consume streams, falling back to the default high/normal/low streams when none are set.
- GetOS · function · L154-L156 — Trivial accessor returning the runtime operating system name.
- GetArch · function · L159-L161 — Trivial accessor returning the runtime CPU architecture.
- GetFFmpegVersion · function · L164-L175 — Runs ffmpeg -version and returns the first output line as the version string, or 'unknown' on failure.
- GetEncoderCapabilities · function · L196-L214 — Detects which whitelisted hardware encoders the local ffmpeg supports by matching encoder names in ffmpeg -encoders output.
- GetIP · function · L221-L259 — Returns the node's IP by preferring a private IPv4 address, falling back to any non-loopback IPv4, without relying on external commands.
- isPrivateIPv4 · function · L262-L264 — Trivial predicate checking whether an IP is private or link-local unicast.
