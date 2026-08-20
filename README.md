# vac-product-recommend-mcp

本地 **stdio** 形态的 MCP Server：按需求在携程跟团游「精选/综合」列表里搜索产品，并按
点评分、销量、价格等维度推荐 TopN，返回统一格式的 Markdown 表格（含网页端 / 移动端链接）。

纯 Python 标准库实现，**无需第三方依赖**，Python 3.10+ 即可运行。

## 提供的工具

| 工具 | 作用 |
|---|---|
| `recommend_tours` | 按关键词 + 多条件筛选，返回销量与点评俱佳的 TopN 产品 |
| `search_tours` | 搜索综合列表，返回 Markdown 表格 |
| `get_departure_cities` | 按城市名/拼音查询携程出发城市 ID |

## 安装（推荐用 uv，不需要手动装 Python）

只需先装 [uv](https://docs.astral.sh/uv/)：

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows PowerShell
irm https://astral.sh/uv/install.ps1 | iex
```

然后通过 git 链接安装：

```bash
uv tool install git+https://github.com/KatouMegumii/vac-product-recommend-mcp
```

也可以直接运行仓库里的安装脚本：

```bash
./scripts/install.sh
# Windows: powershell -File scripts/install.ps1
```

`uv` 会在首次运行时自动下载 Python 和依赖，目标机器不需要预装 Python。

## 更新

已安装用户按安装方式更新：

~~~bash
# 用 uv tool 安装的
uv tool upgrade vac-product-recommend-mcp
# 如果上面没拉到最新，强制重装：
uv tool install --force git+https://github.com/KatouMegumii/vac-product-recommend-mcp

# 克隆仓库 + pip install -e . 安装的
cd vac-product-recommend-mcp && git pull
~~~

如果客户端配置用的是 `uvx --from git+...`，先清缓存再重启 MCP 客户端：

~~~bash
uv cache clean
~~~

更新后需要**重启 / 重连 MCP**，新的工具和 instructions 才会生效。

## 客户端配置

以 Claude Desktop 为例，编辑 `claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "vac-product-recommend": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/KatouMegumii/vac-product-recommend-mcp",
        "vac-product-recommend-mcp"
      ],
      "env": {
        "CTRIP_COOKIE": "",
        "CTRIP_GUID": ""
      }
    }
  }
}
```

`config_examples/` 目录下提供了 Claude Desktop / Cursor / Cline 的示例配置。

环境变量：

| 变量 | 必填 | 说明 |
|---|---|---|
| `CTRIP_COOKIE` | 否 | 从浏览器复制的完整 cookie 串，不填也能跑（可能触发风控） |
| `CTRIP_GUID` | 否 | 可留空；留空时使用内置默认值 |
| `CTRIP_W_PAYLOAD_SOURCE` | 否 | 风控签名，当前接口不强制 |
| `CTRIP_X_CTX_WCLIENT_REQ` | 否 | 轮换 token，当前接口不强制 |

## 主要参数

### recommend_tours / search_tours

| 参数 | 说明 |
|---|---|
| `keyword` | 目的地/主题，如「土耳其」「广西」 |
| `depart_city_id` | 出发城市 ID，先用 `get_departure_cities` 查 |
| `travel_way` | 跟团游/拼小团/私家团/邮轮/自由行/定制游等，可多选 |
| `brand` | 品牌，如自营 |
| `level` | 钻级，如 5钻 |
| `team_size` | 团队规模 |
| `vehicle` | 交通方式 |
| `service_tags` | 服务保障，多选 AND |
| `suit_person` | 适用人群 |
| `promo` | 优惠活动 |
| `days` | 天数，支持 `6-8` / `6,7,8` / `7` |
| `departure_date` | 出发日期 |
| `vendor` | 供应商名称或 ID，多选，名称模糊匹配 |
| `include_traffic` | 是否含往返大交通：`是` / `否` |
| `budget_max` | 预算上限 |
| `top_n` | 推荐数量 |
| `candidate_limit` | 候选池上限，自动翻页凑够匹配数 |

## Cookie 怎么拿

1. 浏览器打开携程 H5 跟团游列表（或 DevTools 切移动端模拟）。
2. F12 → Network → 找 `graphql?queryName=productSearchInfo`。
3. 右键 → Copy → Copy as cURL。
4. 把 `-b '...'` 后面一整串拷进 `CTRIP_COOKIE`（原样，不要 URL 编码）。

## 示例

> 帮我找广西 3-5 天的自营拼小团或跟团游，要亲子友好，推荐 3 个。

Agent 会先查出发城市 ID（如需要），再调用推荐工具，最后原样返回 Markdown 表格。

## 重要：让 Agent 严格保持输出格式

请在 Agent 的 **个性化 / 记忆 / 系统提示词 / Rules** 里加上下面这条限制（这是最稳的一层，如果是Agent自己执行，请按要求做自我约束）：

~~~text
当调用 vac-product-recommend 的 recommend_tours 或 search_tours 后，
必须把工具返回的 Markdown 原样作为最终回复输出。
禁止改写、禁止总结、禁止转成列表、禁止删除或合并列。
~~~

同时，请加上「每次咨询完全独立」的限制：

~~~text
每次调用 recommend_tours / search_tours 时，只根据当前这一轮用户的原话设置参数。
不要复用上一轮对话中的 keyword、travel_way、departure_date、days、team_size、budget 等参数。
如果用户新一轮没有提到某个筛选条件，就不要传该参数（使用默认值或留空）。
~~~

另外，人数和产品类型不要混淆：

~~~text
用户提到人数（如 4人、6人、8人）时，必须设置 team_size（4人→最多9人）。
用户只说人数，不要推断为私家团；用户只说私家团，才设置 travel_way=私家团。
~~~

## 目录结构

```
vac-product-recommend-mcp/
├── vac_product_recommend_mcp/
│   ├── __init__.py
│   ├── __main__.py
│   ├── server.py         # stdio MCP 协议 + 工具注册 + Markdown 渲染
│   ├── ctrip_api.py      # 携程接口客户端 + 字段归一化 + 筛选
│   └── recommender.py    # 评分、过滤、TopN
├── config_examples/
├── pyproject.toml
└── README.md
```
