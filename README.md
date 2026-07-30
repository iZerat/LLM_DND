# LLM DND

一个由 AI 驱动的 D&D 5e 终端游戏。大语言模型担任地下城主（DM），带你体验文字冒险。

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API

复制 `.env.example` 为 `.env`，填入你的 API 信息：

```
API_BASE_URL=https://api.deepseek.com
API_KEY=sk-你的密钥
MODEL_NAME=deepseek-v4-flash
```

兼容任何 OpenAI 格式的 API（DeepSeek、OpenAI、Claude 等）。

### 3. 启动游戏

```bash
python start_game.py
```

## 游戏命令

| 命令 | 说明 |
|------|------|
| `数字` | 选择[选择]中的选项 |
| `自由文本` | 自由行动 |
| `/` | 显示命令列表 |
| `/roll d20+5` | 投骰子 |
| `/status` | 查看角色状态 |
| `/info` | 查看详细角色信息（金钱、性别、年龄等） |
| `/scene` | 查看详细场景信息（海拔、湿度等） |
| `/save` | 保存游戏 |
| `/load` | 读档 |
| `/new` | 新建角色 |
| `/help` | 帮助 |
| `/quit` | 退出 |

## 游戏设计

一轮完整输出包含：场景 → 事件 → 状态（玩家｜目标） → 选择 → 上轮记录

- 目标信息会自动检测缺漏，必要时反问 DM 补全
- 目标按敌我态度着色：敌对（红）、中立（灰）、友方（青绿）
