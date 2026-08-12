package main

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"os"
	"path/filepath"
	"testing"
)

func TestComputeEngineVersionStable(t *testing.T) {
	// 用临时目录构造引擎文件，验证版本计算确定性：相同内容 → 相同版本，内容变化 → 版本变化
	dir := t.TempDir()
	if err := os.MkdirAll(filepath.Join(dir, "seedance_wm"), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "slice.py"), []byte("print(1)\n"), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "seedance_wm", "__init__.py"), []byte("x=1\n"), 0755); err != nil {
		t.Fatal(err)
	}

	v1, err := ComputeEngineVersion(dir)
	if err != nil || v1 == "" {
		t.Fatalf("版本计算失败: %v", err)
	}
	// 相同内容应得到相同版本
	v2, _ := ComputeEngineVersion(dir)
	if v1 != v2 {
		t.Fatalf("相同内容版本应一致: %s != %s", v1, v2)
	}
	// 修改内容应改变版本
	if err := os.WriteFile(filepath.Join(dir, "slice.py"), []byte("print(2)\n"), 0755); err != nil {
		t.Fatal(err)
	}
	v3, _ := ComputeEngineVersion(dir)
	if v1 == v3 {
		t.Fatal("内容变化后版本应改变")
	}
	// 应排除缓存目录
	_ = os.MkdirAll(filepath.Join(dir, "__pycache__"), 0755)
	_ = os.WriteFile(filepath.Join(dir, "__pycache__", "slice.cpython-311.pyc"), []byte("junk"), 0644)
	v4, _ := ComputeEngineVersion(dir)
	if v4 != v3 {
		t.Fatal("缓存文件不应影响版本")
	}
}

func TestExtractTarGz(t *testing.T) {
	var buf bytes.Buffer
	gw := gzip.NewWriter(&buf)
	tw := tar.NewWriter(gw)
	content := []byte("print('hi')\n")
	_ = tw.WriteHeader(&tar.Header{Name: "slice.py", Mode: 0755, Size: int64(len(content))})
	_, _ = tw.Write(content)
	_ = tw.WriteHeader(&tar.Header{Name: "sub/", Typeflag: tar.TypeDir, Mode: 0755})
	_ = tw.Close()
	_ = gw.Close()

	dest := filepath.Join(t.TempDir(), "engines")
	if err := extractTarGz(buf.Bytes(), dest); err != nil {
		t.Fatalf("解压失败: %v", err)
	}
	data, err := os.ReadFile(filepath.Join(dest, "slice.py"))
	if err != nil || string(data) != "print('hi')\n" {
		t.Fatalf("解压内容不正确: %v %q", err, data)
	}
}

func TestExtractTarGzPathTraversal(t *testing.T) {
	var buf bytes.Buffer
	gw := gzip.NewWriter(&buf)
	tw := tar.NewWriter(gw)
	evil := []byte("x")
	_ = tw.WriteHeader(&tar.Header{Name: "../../evil.py", Mode: 0755, Size: int64(len(evil))})
	_, _ = tw.Write(evil)
	_ = tw.Close()
	_ = gw.Close()

	if err := extractTarGz(buf.Bytes(), t.TempDir()); err == nil {
		t.Fatal("路径穿越应当被拦截，但未报错")
	}
}
