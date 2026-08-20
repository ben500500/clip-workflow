# slice-worker/config.go · [[slice-worker-node]]

- Config · struct · L14-L43 — Config
- DefaultNodeID · function · L50-L66 — func DefaultNodeID() string
- DefaultConfig · function · L69-L87 — func DefaultConfig() *Config
- LoadConfig · function · L90-L114 — func LoadConfig(path string) (*Config, error)
- ClampCPUPercent · function · L117-L125 — func ClampCPUPercent(v int) int
- HeartbeatTTL · method · L128-L133 — func (c *Config) HeartbeatTTL() time.Duration
- EffectiveConsumeStreams · method · L146-L151 — func (c *Config) EffectiveConsumeStreams() []string
- GetOS · function · L154-L156 — func GetOS() string
- GetArch · function · L159-L161 — func GetArch() string
- GetFFmpegVersion · function · L164-L175 — func GetFFmpegVersion() string
- GetEncoderCapabilities · function · L196-L214 — func GetEncoderCapabilities() []string
- GetIP · function · L221-L259 — func GetIP() string
- isPrivateIPv4 · function · L262-L264 — func isPrivateIPv4(ip net.IP) bool
