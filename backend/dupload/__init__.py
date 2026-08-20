"""dupload 推送到下载平台包（并入 + 可剥离）。

对接 192.168.1.21:8800 的 dramaupload / dupload 独立服务：
剧目详情录入素材链接（shareUrl）后，一键调用 `POST /api/dupload/tasks`
（action=only_download）把该剧目推给下载平台去下载入库。
"""
