# Blender MCP × Qoder 接入

让 Qoder Desktop 通过 MCP 控制本机 Blender。MCP 服务来自 [ahujasid/mcp-for-blender](https://github.com/ahujasid/mcp-for-blender)（MIT，PyPI 包名 `mcp-for-blender`）；本仓库只保存 Qoder 侧的接入配置、安装/探活脚本和实测说明，不包含上游代码。

链路：

```
Qoder Desktop → stdio MCP (uvx mcp-for-blender) → TCP 127.0.0.1:9876 → Blender 插件
```

## 实测环境

| 项 | 版本 |
| --- | --- |
| OS | Windows 10/11 x64 |
| Blender | 5.2.2 LTS |
| mcp-for-blender | 2.2.6 |
| Blender 插件 | 1.8（protocol 13） |
| 端口 | 9876 |
| Qoder | Desktop，用户级 MCP |

已验证：MCP 握手、`tools/list`（9 个工具）、Blender GUI 下读取场景。

前置条件：Blender 3.0+（实测 5.2.2 LTS）、Python 3.10+、uv（`uvx` 随 uv 一起安装）、Blender 以 GUI 方式运行。

## 快速开始

### 1. 安装 uv

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

新开一个终端，确认：

```powershell
uvx --version
```

### 2. 安装 Blender 插件

```powershell
uvx mcp-for-blender install-addon
```

该命令把插件复制到已发现的 Blender 用户插件目录。可以先看会装到哪里：

```powershell
uvx mcp-for-blender addon-paths
```

也可以直接运行本仓库的脚本：

```powershell
powershell -ExecutionPolicy ByPass -File scripts/install.ps1
```

### 3. 在 Blender 里启用插件

1. 打开 Blender（必须是 GUI，不能用 `--background`）。
2. `Edit → Preferences → Add-ons`，搜索并勾选 **Interface: MCP for Blender**。
3. 在 Preferences 右上角菜单里点 **Save Preferences**，避免下次启动又变回未启用。
4. 在 3D Viewport 按 `N`，打开侧栏的 **MCP for Blender** 标签页；应显示 `Connected on port 9876`。若显示 `Not connected`，点 **Connect to MCP server**。

插件的 **Auto-Start Server** 默认开启（Scene 属性 `blendermcp_auto_start_server`），正常情况下 Blender 一打开就会监听 9876。

### 4. 注册到 Qoder

编辑 `%USERPROFILE%\.qoder-cn\settings.json`，在 `mcpServers` 下加入（`command` 用绝对路径）：

```json
"blender": {
  "command": "C:\\Users\\<你>\\.local\\bin\\uvx.exe",
  "args": ["mcp-for-blender"]
}
```

完整片段见 [`qoder/blender.mcp.json`](qoder/blender.mcp.json)。保存后重启 Qoder 或新开一个会话；MCP 工具在会话启动时加载，旧会话里不会出现。

## 验证

不经过 Qoder，直接验证 stdio 服务：

```powershell
python scripts/probe_blender_mcp.py
```

预期输出（节选）：

```
INIT: MCP for Blender 1.30.0 (protocol 2024-11-05)
TOOL COUNT: 9
TOOLS: get_addon_status, disable_telemetry, get_scene_info, execute_blender_code, record_trajectory_feedback, look, generate_3d, search_assets, import_asset
```

`serverInfo.version` 的 `1.30.0` 与它依赖的 `mcp` 包版本一致，不是 `mcp-for-blender` 的版本；包版本用 `uvx --from mcp-for-blender python -c "import importlib.metadata as m; print(m.version('mcp-for-blender'))"` 查。探活脚本需要 Python 3.8+（只用标准库）。

下面这条会真的进 Blender 读场景，需要 Blender 开着且 9876 在监听：

```powershell
python scripts/probe_blender_mcp.py --call get_scene_info
```

Blender 没开时，这个调用会返回 `isError: false` 但正文以 `Error getting scene info` 开头；探活脚本会把这种正文判为失败并以退出码 1 结束。

## 可选项

| 环境变量 | 默认 | 作用 |
| --- | --- | --- |
| `BLENDER_HOST` | `127.0.0.1` | 插件监听地址 |
| `BLENDER_PORT` | `9876` | 插件监听端口 |
| `BLENDER_MCP_SAFE_MODE` | 关 | 设为 `1` 后，服务端在把代码送进 Blender 前做 AST 白名单校验，拦截文件/网络/进程与解释器逃逸；只保护 MCP 路径，不是沙箱 |
| `DISABLE_TELEMETRY` | 关 | 设为 `true` 关闭匿名使用统计；内容采集本来就是 opt-in |

这些变量写在 Qoder 的 `env` 里即可；不写就用默认值。

## 常见问题

| 现象 | 原因 / 处理 |
| --- | --- |
| Qoder 里看不到 `blender` 工具 | 新开一个会话；MCP 工具只在会话启动时加载 |
| `Could not connect to Blender` / `Connection refused` | Blender 没开、插件没启用，或 9876 没在监听；先看 Blender 侧栏是否 `Connected on port 9876` |
| Blender 侧栏一直 `Not connected` | 端口被占用（`netstat -ano \| findstr :9876`）；换端口需同时改插件和 Qoder 的 `BLENDER_PORT` |
| 无头模式连不上 | 自动启动路径 `_blendermcp_ensure_server_running()` 和 `start()` 都有 `bpy.app.background` 判断；`--background` 永远不会开 socket，只能用 GUI |
| 脚本启用插件后重启又关了 | 无头/脚本里 `addon_utils.enable(..., default_set=True)` 只改内存；还要 `bpy.ops.wm.save_userpref()` |
| `uvx` 找不到 | Qoder 不继承你的 shell PATH；`command` 写 `C:\Users\<你>\.local\bin\uvx.exe` 绝对路径 |
| 首次调用很慢 / 失败 | `uvx` 第一次要下载包和 Python 依赖；先在终端跑一次 `uvx mcp-for-blender --help` 预热 |

## 更新与卸载

```powershell
uvx mcp-for-blender update
```

更新会同时升级 MCP 服务和已安装的 Blender 插件，之后重启 Blender 和 Qoder 会话。

卸载：在 Blender Preferences → Add-ons 里移除 **MCP for Blender**，从 `settings.json` 删除 `blender` 条目。`uvx` 的包缓存在 `%LOCALAPPDATA%\uv\cache`，需要时用 `uv cache clean` 清理。

## 安全提示

`execute_blender_code` 会在你的 Blender 进程里执行任意 Python，这是该插件的核心功能。动手前先保存 `.blend`；处理不可信资产/文本时建议打开 `BLENDER_MCP_SAFE_MODE=1`。插件 socket 本身接受本机任意进程的连接，安全模式只约束 MCP 这一条路径。

## 许可与来源

本仓库的配置、脚本与文字为 MIT。MCP 服务与 Blender 插件来自 [ahujasid/mcp-for-blender](https://github.com/ahujasid/mcp-for-blender)（MIT），版权归原作者。本项目与 Blender Foundation 无关联。
