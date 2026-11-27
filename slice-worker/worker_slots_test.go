package main

import (
	"encoding/json"
	"fmt"
	"os"
	"sync/atomic"
	"testing"
	"time"

	"github.com/redis/go-redis/v9"
)

func TestIdleFetchReservationIsNotReportedAsRunningTask(t *testing.T) {
	w := &Worker{config: &Config{MaxConcurrent: 1}}
	if !w.tryReserveSlot() {
		t.Fatal("空闲 Worker 应能预占槽位")
	}
	if got := atomic.LoadInt32(&w.currentTasks); got != 1 {
		t.Fatalf("内部预占槽位应为 1，实际 %d", got)
	}
	if got := w.GetCurrentTaskCount(); got != 0 {
		t.Fatalf("等待消息的预占槽位不得计为运行任务，实际 %d", got)
	}

	w.runningTasks.Store("task-running", &RunningTask{})
	if got := w.activeTaskCount(); got != 1 {
		t.Fatalf("已登记运行任务数应为 1，实际 %d", got)
	}
	w.runningTasks.Delete("task-running")
	w.releaseReservedSlot()
	if got := w.GetCurrentTaskCount(); got != 0 {
		t.Fatalf("任务退出后运行任务数应为 0，实际 %d", got)
	}
	if got := atomic.LoadInt32(&w.currentTasks); got != 0 {
		t.Fatalf("预占槽位应已归还，实际 %d", got)
	}
}

func TestReserveSlotHonorsMaxConcurrent(t *testing.T) {
	w := &Worker{config: &Config{MaxConcurrent: 1}}
	if !w.tryReserveSlot() {
		t.Fatal("首次预占应成功")
	}
	if w.tryReserveSlot() {
		t.Fatal("达到 MaxConcurrent 后不得再次预占")
	}
	w.releaseReservedSlot()
	if !w.tryReserveSlot() {
		t.Fatal("归还槽位后应能再次预占")
	}
	w.releaseReservedSlot()
}

func TestClaimStaleTasksPreservesActiveLeaseOwner(t *testing.T) {
	redisURL := os.Getenv("TEST_REDIS_URL")
	if redisURL == "" {
		t.Skip("设置 TEST_REDIS_URL 后运行真实 Redis PEL 回归")
	}
	r, err := NewRedisClient(redisURL)
	if err != nil {
		t.Fatal(err)
	}
	defer r.Close()

	suffix := fmt.Sprint(time.Now().UnixNano())
	stream := "slice:test:pending:" + suffix
	activeID := "active-" + suffix
	orphanID := "orphan-" + suffix
	defer r.client.Del(r.ctx, stream, fmt.Sprintf("slice:task:%s", activeID), fmt.Sprintf("slice:task:%s", orphanID))
	if err := r.CreateConsumerGroup(stream, "workers"); err != nil {
		t.Fatal(err)
	}
	for _, taskID := range []string{activeID, orphanID} {
		data, err := json.Marshal(SliceTask{TaskID: taskID})
		if err != nil {
			t.Fatal(err)
		}
		if err := r.client.XAdd(r.ctx, &redis.XAddArgs{Stream: stream, Values: map[string]interface{}{"data": string(data)}}).Err(); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := r.client.XReadGroup(r.ctx, &redis.XReadGroupArgs{Group: "workers", Consumer: "active-owner", Streams: []string{stream, ">"}, Count: 2}).Result(); err != nil {
		t.Fatal(err)
	}
	if err := r.client.HSet(r.ctx, fmt.Sprintf("slice:task:%s", activeID), map[string]interface{}{"status": "running", "lease": time.Now().Unix()}).Err(); err != nil {
		t.Fatal(err)
	}
	if err := r.client.HSet(r.ctx, fmt.Sprintf("slice:task:%s", orphanID), "status", "pending").Err(); err != nil {
		t.Fatal(err)
	}
	time.Sleep(10 * time.Millisecond)

	claimed, err := r.ClaimStaleTasks([]string{stream}, "workers", "recovery", 5*time.Millisecond)
	if err != nil {
		t.Fatal(err)
	}
	if len(claimed) != 1 || claimed[0].Task.TaskID != orphanID {
		t.Fatalf("只应认领无活跃租约的孤儿任务，实际 %+v", claimed)
	}
	pending, err := r.client.XPendingExt(r.ctx, &redis.XPendingExtArgs{Stream: stream, Group: "workers", Start: "-", End: "+", Count: 10}).Result()
	if err != nil {
		t.Fatal(err)
	}
	owners := make(map[string]string)
	for _, p := range pending {
		owners[p.ID] = p.Consumer
	}
	for _, p := range pending {
		var task SliceTask
		msgs, err := r.client.XRangeN(r.ctx, stream, p.ID, p.ID, 1).Result()
		if err != nil || len(msgs) != 1 {
			t.Fatalf("读取 PEL 消息失败: %v", err)
		}
		data, _ := msgs[0].Values["data"].(string)
		if err := json.Unmarshal([]byte(data), &task); err != nil {
			t.Fatal(err)
		}
		if task.TaskID == activeID && p.Consumer != "active-owner" {
			t.Fatalf("活跃任务 PEL 所有权被抢走: %+v", p)
		}
		if task.TaskID == orphanID && p.Consumer != "recovery" {
			t.Fatalf("孤儿任务未转交 recovery: %+v", p)
		}
	}
	if len(owners) != 2 {
		t.Fatalf("PEL 应保留两条消息，实际 %+v", owners)
	}
}

func TestFreshTaskLeaseFilter(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	cases := []struct {
		name string
		hash map[string]string
		want bool
	}{
		{name: "fresh running lease", hash: map[string]string{"status": "running", "lease": fmt.Sprint(now.Unix() - 10)}, want: true},
		{name: "stale running lease", hash: map[string]string{"status": "running", "lease": fmt.Sprint(now.Unix() - 301)}},
		{name: "missing lease", hash: map[string]string{"status": "running"}},
		{name: "malformed lease", hash: map[string]string{"status": "running", "lease": "bad"}},
		{name: "completed", hash: map[string]string{"status": "completed", "lease": fmt.Sprint(now.Unix() - 10)}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := hasFreshTaskLease(tc.hash, now); got != tc.want {
				t.Fatalf("hasFreshTaskLease() = %v, want %v", got, tc.want)
			}
		})
	}
}
