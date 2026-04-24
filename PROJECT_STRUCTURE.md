# 项目目录职责说明

这份文档用于快速说明当前项目各目录和核心文件的职责，方便后续个人维护、定位代码和继续重构。

## 根目录

- `main_island.py`
  - 当前主运行入口。
  - 负责启动灵动岛 UI 主流程，并按参数选择 SIFT 或 AI 跟踪引擎。

- `main_ai.py`
  - AI 方案兼容启动入口。
  - 目前主要转发到 `Plan_AI/main_ai.py`，用于后续 AI 方案独立调试或参考。

- `base.py`
  - 跟踪器公共接口层。
  - 定义 `BaseTracker`、`TrackResult`、`TrackState` 等主链公共类型。

- `route_manager.py`
  - 路线系统核心管理器。
  - 负责路线读取、可见性、进度持久化、地图绘制时的路线节点状态处理。

- `config.py`
  - 配置读写与默认配置定义。

- `config.json`
  - 运行期配置文件。

- `PROJECT_STRUCTURE.md`
  - 当前这份目录职责说明。

- `README.md`
  - 项目说明文档。

- `requirements.txt`
  - Python 依赖清单。

- `routes/`
  - 路线数据目录。
  - 包含路线文件、最近路线、已选路线和节点进度等持久化数据。

- `tools/`
  - 一次性工具脚本与工具数据。
  - 当前放的是地图下载、打点绘制和相关原始数据，不属于主运行链。

- `Plan_SIFT/`
  - SIFT 方案代码归档目录。
  - 当前主程序如选择 SIFT 引擎，会实际使用这里的实现。

- `Plan_AI/`
  - AI 方案代码归档目录。
  - 当前保留供后续独立优化、重新适配灵动岛 UI 时参考和接入。

## `ui_island/`

`ui_island` 是当前灵动岛 UI 主包。根目录现在只保留“包入口”，真正实现已经按职责拆进子目录。

### 入口文件

- `ui_island/__init__.py`
  - 包对外入口。
  - 当前统一导出 `IslandWindow`。

- `ui_island/island.py`
  - 兼容入口。
  - 作用是保留旧导入路径，内部转发到新位置。

## `ui_island/app/`

放主窗口装配层，也就是“应用协调层”。

- `window.py`
  - `IslandWindow` 主实现。
  - 当前主要负责：
    - 初始化 tracker、route manager、stores、controllers、state
    - Qt 生命周期桥接
    - 顶层信号连接
    - 少量顶层 UI 协调

- `window_view.py`
  - 主窗口视图构建。
  - 负责搭建头部、地图区、路线区、侧边栏等控件结构。

- `window_state_bridge.py`
  - 状态桥接层。
  - 把 `state/models.py` 中的 dataclass 字段桥接成窗口层兼容属性，减少改造期的接口断裂。

## `ui_island/controllers/`

放控制器层，承接具体业务逻辑。

- `route_panel_controller.py`
  - 路线侧栏与当前追踪路线面板逻辑。
  - 包括路线列表构建、重命名、删除、搜索、最近常用、当前追踪路线、重置进度等。

- `window_mode_controller.py`
  - 窗口模式与几何控制。
  - 包括：
    - `PAUSED / TRACKING_STABLE / TRACKING_INERTIAL / TRACKING_LOST / MAXIMIZED`
    - 窗口尺寸与几何恢复
    - sidebar 折叠/展开和宽度策略
    - 尺寸持久化

- `tracking_controller.py`
  - 跟踪状态逻辑。
  - 包括：
    - 跟踪循环
    - 开始/暂停导航
    - LOST/SEARCHING/LOCKED/INERTIAL 状态映射
    - 告警与头部动作显隐

- `interaction_controller.py`
  - 交互辅助层。
  - 包括窗口边缘 resize、侧边栏拖拽、嵌套滚轮处理等。

- `hotkey_controller.py`
  - 快捷键监听管理。
  - 当前主要负责 `Alt+~` 锁定/解锁热键。

## `ui_island/views/`

放独立视图组件。

- `map_view.py`
  - 地图视图主组件。
  - 负责地图缩放、拖拽、双击重定位、渲染玩家位置和路线叠加。

## `ui_island/widgets/`

放小型可复用控件。

- `route_widgets.py`
  - 路线侧栏与当前追踪路线相关的小组件。

- `restore_icon.py`
  - 主窗口最小化后的恢复胶囊图标。

## `ui_island/dialogs/`

放弹窗与轻提示相关实现。

- `base.py`
  - 通用弹窗基类和基础对话框壳。

- `toast.py`
  - 轻提示组件。

- `settings_dialog.py`
  - 设置窗口实现。

- `minimap_selector.py`
  - 小地图校准流程实现。

## `ui_island/design/`

放视觉设计常量和样式定义。

- `theme.py`
  - 旧的主题常量集中地。
  - 当前仍有不少模块直接依赖这里的颜色、尺寸和 QSS 常量。

- `tokens.py`
  - 设计 token。

- `qss.py`
  - QSS 相关工具和样式收口。

- `strings.py`
  - 文案常量。

- `button_specs.py`
  - 头部按钮等规格化配置。

## `ui_island/services/`

放服务层与持久化访问封装。

- `settings_gateway.py`
  - 对 `config` 的集中访问。

- `window_prefs_store.py`
  - 窗口几何、sidebar、尺寸偏好读写。

- `recent_routes_store.py`
  - 最近路线读写。

- `settings_schema.py`
  - 设置项字段定义与表单结构描述。

## `ui_island/state/`

放窗口运行期状态模型。

- `models.py`
  - 以 dataclass 形式承载窗口模式、布局偏好、路线面板、跟踪状态、热键状态。

## `ui_island/platform/`

放平台相关适配层。

- `win_overlay.py`
  - Windows 覆盖层行为适配。
  - 包括置顶、点击穿透、overlay flags 等。

## 当前维护建议

- 日常改 UI 结构：
  - 优先看 `ui_island/app/window_view.py`

- 改窗口行为、尺寸、sidebar：
  - 优先看 `ui_island/controllers/window_mode_controller.py`

- 改导航状态、丢失/搜索/锁定行为：
  - 优先看 `ui_island/controllers/tracking_controller.py`

- 改路线列表、最近常用、重置进度：
  - 优先看 `ui_island/controllers/route_panel_controller.py`

- 改地图交互：
  - 优先看 `ui_island/views/map_view.py`

- 改样式和视觉常量：
  - 优先看 `ui_island/design/`，其次看 `ui_island/design/theme.py`

## 后续若继续优化，建议优先级

1. 清理部分文件中的历史编码脏字和旧文案残留
2. 逐步减少对 `design/theme.py` 的直接依赖，统一收口到 `design/` 内部结构