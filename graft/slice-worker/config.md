# slice-worker/config.go

- Config · struct · L14-L39 — Config
- DefaultNodeID · function · L46-L62 — func DefaultNodeID() string
- DefaultConfig · function · L65-L82 — func DefaultConfig() *Config
- LoadConfig · function · L85-L109 — func LoadConfig(path string) (*Config, error)
- ClampCPUPercent · function · L112-L120 — func ClampCPUPercent(v int) int
- HeartbeatTTL · method · L123-L128 — func (c *Config) HeartbeatTTL() time.Duration
- EffectiveConsumeStreams · method · L141-L146 — func (c *Config) EffectiveConsumeStreams() []string
- GetOS · function · L149-L151 — func GetOS() string
- GetArch · function · L154-L156 — func GetArch() string
- GetFFmpegVersion · function · L159-L170 — func GetFFmpegVersion() string
- GetEncoderCapabilities · function · L191-L209 — func GetEncoderCapabilities() []string
- GetIP · function · L216-L254 — func GetIP() string
- isPrivateIPv4 · function · L257-L259 — func isPrivateIPv4(ip net.IP) bool
