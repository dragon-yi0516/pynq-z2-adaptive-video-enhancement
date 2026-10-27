# 相关工作与定位（GitHub 调研，2026-10-22）

> 用途：补报告“选题背景/创新点/前人做过什么”。不是拿别人项目当实测，
> 只用于说明技术路线差异。

## 对照表

| 项目 | 主要能力 | 与这个项目的关系 |
|---|---|---|
| [xupsh/Pynq-CV-OV5640](https://github.com/xupsh/Pynq-CV-OV5640) | PYNQ + OV5640 基础采集、VDMA/HDMI、多个固定 HLS 滤镜 | 这个项目的基础 BD 来源；我们在其上增加逐像素统计、MLP 与自适应闭环 |
| [amd/mini-isp](https://github.com/amd/mini-isp) | 极简固定 ISP：decompanding、黑电平、数字增益、demosaic、CCM、Gamma LUT；1/2/4 PPC；MIT/REUSE | 它提供固定画质管线；上游把 AE/AWB 和对比度增强列在范围外。这个项目补的是“场景自适应控制层”，定位是接在完整 ISP 后面使用 |
| [Kaarannnnnnnn/video-pipeline-core](https://github.com/Kaarannnnnnnn/video-pipeline-core) | DVP→FrameSync→Demosaic→White Balance→Gamma LUT→TNR；Python golden model/error heatmap；Vivado util/timing/power/DRC 报告 | 它的 WB/Gamma/TNR 更完整；这个项目侧重自适应模式和 PARAM，WB/TNR 留在完整 ISP 层。其 Future Work 提到“adaptive gamma based on scene luminance”，与本项目的闭环方向一致 |
| [sarvesh-builds/64feature_RGB_NN](https://github.com/sarvesh-builds/64feature_RGB_NN) | PYNQ-Z2 上 64 维 RGB 特征 + INT8 MLP，用于 FOD 检测；HLS/CSim/综合/IP | 说明 PYNQ-Z2 上做轻量 MLP 是可行路线；这个项目用 3 维全局特征和四象限规则，模型更小，重点放在增强而不是检测 |
| [khuonglha1918/PYNQ-Z2_OV7670_Non-FiFo_Camera](https://github.com/khuonglha1918/PYNQ-Z2_OV7670_Non-FiFo_Camera) | OV7670→HDMI、OSD 文本/FPS、按键切模式 | OSD/FPS 是直观的演示增强；这个项目展示画面时使用 Jupyter 和 HDMI 分屏 |
| [shenguangmu/gesture_pl](https://github.com/shenguangmu/gesture_pl) | PYNQ-Z2 PL 预处理、720p60 HDMI、HLS、HANDOFF/sim/skill/report 结构 | 工程包装很值得借鉴；该 README 把摄像头通路 bring-up 和 720p60 HDMI 列为后续项。本项目是 720p30，采集、显示和长时运行已经完成实测 |
| [fangdut/TileLab-PYNQ-Z2](https://github.com/fangdut/TileLab-PYNQ-Z2) | PYNQ-Z2 720p60 检测/标框 + 以太网证据传输 | 说明 Z2 可以上 720p60，但需要完整改造 TMDS、时序和传输链路；本轮优先保证 720p30 的证据完整 |

## 这个项目的定位

这个项目的定位是：

> 在固定 demosaic/ISP 之后，加一层**可解释的场景自适应控制**：
> PL 逐像素统计 + 四象限，PS 用 3-8-3 MLP + 空间规则决策，
> 连续 PARAM 执行，帧边界切换，并用 hard pair/真实场景/失败场景/1h soak 形成验证记录。

这正好补了 mini-ISP 的空白：mini-ISP 把固定画质做好，但不做 AE/AWB/对比度；
WB/CCM/TNR 交给完整 ISP；本项目回答的是“**这一帧该用哪种增强、强度多大**”。

## 答辩时的三句话

1. **和固定 ISP 的区别**：mini-ISP 是固定管线；本项目在其后加入闭环控制器，
   根据亮度和空间布局切换模式与强度。
2. **和“亮度阈值”的区别**：同亮度 hard pair 中，MLP 都判 0，
   四象限把亮窗场景改判 mode 1；纯 MLP 0.750，加规则 1.000。
3. **和“大模型”的区别**：3-8-3 Q8.8 MLP 只有 59 个参数，
   资源低、可解释、可逐位复算；不是 CNN，也不假装是。

## 本轮不采用的扩展

| 借鉴点 | 来源 | 为什么不一周做 |
|---|---|---|
| White Balance / Gamma LUT / CCM | mini-ISP、video-pipeline-core | 要改像素链、BRAM/LUT、重出 bit、重跑全部证据；一周风险高 |
| Motion-adaptive TNR | video-pipeline-core | 需要帧缓存/时序对齐；与这个项目“单帧自适应”不是同一层 |
| 720p60 | gesture_pl、TileLab | 要改传感器/像素时钟/TMDS/VDMA/HDMI；会推翻现有 29.76fps 证据 |
| 64 维 RGB 特征 + INT8 MLP | 64feature_RGB_NN | 需要重新采集 64 维特征并重训/重出 bit；当前 3 维+四象限已够讲清闭环 |
| OSD 文本/FPS | OV7670 项目 | 可见效果好，但要改 HDMI 像素链；一周内不如把报告/视频做好 |

## 报告引用建议

在 1.1/1.5 或附录加一句：

> 与 AMD mini-ISP 等固定 ISP 相比，这个项目不重复实现 demosaic/CCM/Gamma，
> 而是在其输出后增加 MLP + 四象限的闭环控制；与固定 HLS 滤镜工程相比，
> 这个项目的控制参数随场景连续变化，并用同亮度 hard pair 验证空间信息确实参与决策。