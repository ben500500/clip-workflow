# backend/app/api/watermark.py

- gen_task_name · function · L46-L65 — 生成日期+4位自增序列的任务名称，优先用 Redis 跨进程全局自增并在日期切换时自动归 1，Redis 不可用时回退到进程内计数。
- _fallback_seq · function · L71-L74 — Redis 不可用时的进程内自增序列回退实现，保证任务命名不抛错。
- WatermarkRunRequest · class · L90-L114 — 去水印任务请求体，聚合四套引擎（RAiW/Seedance/seedance_wm/remove_mask）的全部可选参数及待处理文件列表。
- WatermarkVideoItem · class · L117-L131 — 单条视频的响应数据模型，描述去水印处理状态、进度、错误及输出/源文件链接。
- WatermarkTaskItem · class · L134-L150 — 去水印任务级响应数据模型，汇总引擎、状态、进度及各视频计数。
- WatermarkTaskDetail · class · L153-L154 — 任务详情响应模型，在任务基础上扩展包含其下所有视频列表。
- WatermarkDeleteRequest · class · L157-L158 — 批量删除任务的请求体，携带待删除的任务 id 列表。
- _serialize_video · function · L166-L186 — 将视频 ORM 记录序列化为 API 响应字典，并计算处理耗时。
- _serialize_task · function · L189-L215 — 将任务 ORM 记录序列化为 API 响应字典，计算耗时并回退来源提示词记录 id 以保持去水印→发布链路。
- upload_watermark_video · function · L224-L275 — 上传单条待去水印视频到 MinIO watermark-raw 桶，校验文件名与大小上限并返回 source_file_key 供后续任务提交。
- run_watermark_task · function · L279-L428 — 创建去水印任务：校验引擎与文件数、按引擎构造选项、写入任务与子视频记录并异步派发 Celery 处理。
- list_watermark_tasks · function · L432-L460 — 按创建时间倒序返回最近 200 个任务，并通过批量查询子视频回退来源提示词记录 id 避免 N+1。
- get_watermark_task · function · L464-L511 — 返回单个任务详情，为每条视频生成源/输出文件的预签名直链，并从子视频回退来源提示词记录。
- delete_watermark_task · function · L515-L556 — 删除单个任务：运行中先标记取消让 Celery 感知中断，再删除 MinIO 源/输出文件（保留归属提示词记录的源视频）。
- batch_delete_watermark_tasks · function · L560-L608 — 批量删除多个任务及其 MinIO 资源文件。
- delete_watermark_video · function · L612-L641 — 删除单条视频记录及其 MinIO 源/输出文件。
- download_watermark_video · function · L645-L671 — 为单条视频生成输出文件的预签名下载链接。
- batch_download_watermark_videos · function · L675-L711 — 为多条视频批量生成输出文件的预签名下载链接。
