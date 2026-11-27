package main

import (
	"strings"
	"testing"
)

func TestRedactedRedisURL(t *testing.T) {
	raw := "redis://:p%40ss%2Fword@127.0.0.1:6379/0"
	got := RedactedRedisURL(raw)
	if strings.Contains(got, "p%40ss%2Fword") || strings.Contains(got, "p@ss/word") {
		t.Fatalf("Redis 密码未脱敏: %s", got)
	}
	if got != "redis://:***@127.0.0.1:6379/0" {
		t.Fatalf("脱敏结果不符合预期: %s", got)
	}
}

func TestRedactedRedisURLWithoutPassword(t *testing.T) {
	raw := "redis://127.0.0.1:6379/0"
	if got := RedactedRedisURL(raw); got != raw {
		t.Fatalf("无密码地址被意外修改: %s", got)
	}
}
