# engines/remove_mask_remover.py · [[opencv-watermark-remover]]

Remove Mask 去水印引擎，基于 ROI + cv2.inpaint 方案，支持自动检测水印带、预置 ROI 匹配、inpaint/crop 两种去水印模式及多种预设参数方案。

- _load_sampled_frames · function · L87-L103 — 均匀抽帧用于快速分析，不读全片，返回采样帧栈和总帧数。
- _semi_white_mask · function · L106-L125 — 检测半透明白色水印像素：要求 min 通道高、低饱和、且明显亮于局部背景，并做形态学开运算与膨胀。
- _static_consistency_filter · function · L128-L169 — 通过时间一致性过滤剔除移动亮色主体（白发/人脸）误判，仅剔除一致性极低且非细长条的大块候选。
- _detect_text_bands · function · L172-L239 — 逐帧在四角区域检测水平文字水印带，通过行/列投影阈值切分候选框并做时间一致性过滤。
- _detect_corner_heatmap · function · L242-L318 — 基于时间一致性热力图 + 边缘先验的四角水印带检测器，解决弱/淡色水印漏检问题。
- _cluster_boxes · function · L321-L393 — 对候选框做 y 直方图峰值分带 + 带内 x 聚类，输出带置信度（真实覆盖帧比例）的水印带，含高度守卫。
- _merge_bands · function · L396-L439 — 把同一行带内 y 重叠且 x 接近的候选框合并为完整覆盖框，合并后过高/过宽则回退为最大置信度单框。
- analyze_video · function · L442-L508 — 自动分析任意视频检测水印带，按四角身份汇总 top/bottom 候选，生成人类可读报告，检测不到时回退全角大框。
- analysis_to_rois · function · L511-L645 — 把分析结果转成 inpaint 用的 ROI dict，按 x 中心判断左右角实现四角全覆盖，过滤低置信度/过高带，未检测到则回退全角大框。
- _band_ok · function · L530-L532 — 判断候选带是否可作为 ROI：置信度足够且高度符合文字水印特征。
- _to_roi · function · L534-L537 — 把候选带坐标加上 margin buffer 并裁剪到画面边界，生成 ROI 元组。
- _merge_y_overlap · function · L539-L559 — 合并 y 重叠的 ROI 列表，避免同一角多个分段水印被拆成多个小 ROI。
- _emit · function · L561-L567 — 把合并后的 ROI 列表按前缀写入 rois dict（支持 TL/TL2/TL3 等多候选命名）。
- _corner_edge_ok · function · L578-L585 — 判断候选带是否靠近画面边缘（左右 15% 或上下 12%），用于抑制中央亮色主体误判。
- _corner_edge_ok · function · L613-L620 — 判断候选带是否靠近画面边缘，用于抑制中央亮色主体误判。
- process_crop · function · L648-L762 — 裁切去水印模式：裁掉包含水印的上下水平带，等比放大回原始分辨率并左右对称居中裁回原始宽度。
- process · function · L765-L872 — inpaint 去水印模式：对每个 ROI 用 cv2.inpaint 插值修复，保留原始分辨率/帧率/编码，音频流复制。
- main · function · L875-L1034 — CLI 入口：解析参数、匹配预置 ROI 或自动检测、选择预设方案、执行 inpaint/crop 处理并输出进度。
