# Release 3.0.1 外部初始化会话接口说明

本文是给外部系统联调用的独立接口说明。当前线上环境已按 `3.0.1` 版本运行，联调用例以 `https://www.gaotuzhiyuan.com` 为准。

实现设计和内部幂等说明见：[external-session-initialize-api-design.md](external-session-initialize-api-design.md)

## 1. 联调范围

当前线上可直接联调的部分：

1. 外部初始化会话接口
2. 会话列表
3. 会话详情
4. 方案工作台摘要
5. 导出志愿结果

其中，`/inner/**` 下的接口更适合联调核对，不建议外部系统长期直接依赖。

## 2. 线上地址

- 生产域名：`https://www.gaotuzhiyuan.com`
- 会话列表页：`https://www.gaotuzhiyuan.com/assistant-pc/session`
- 会话详情页：`https://www.gaotuzhiyuan.com/assistant-pc/sessionDetailV2?chatSessionId={id}`

## 3. 调用顺序

### 第一步：登录获取系统 `loginToken`

接口：

```http
POST /gaotu-assistant-bot/chat/user/login/by-token
```

请求体：

```json
{
  "channel": "gaotu",
  "token": "外部系统自己的授权 token"
}
```

说明：

- `channel` 是登录渠道，不是业务请求头里的 `pf`。
- 当前初始化接口的业务请求头里，`pf` 请传 `WEB`。
- 如果你已经拿到了当前系统的 `loginToken`，这一步可以跳过。

### 第二步：初始化会话

接口：

```http
POST /gaotu-assistant-bot/chat/{tenantId}/integration/v1/session/initialize
```

兼容路径：

```http
POST /gaotu-assistant-bot/chat/{tenantId}/integration/session/initialize
```

当前 `tenantId` 线上通常为 `1`，以实际租户为准。

说明：

- 当前线上 `3.0.1` 已有外部系统对接无版本路径，后续发布会继续保留该路径。
- `v1` 是推荐的稳定版本路径；无版本路径作为兼容入口保留，便于已接入系统继续联调和上线。
- 两个路径的请求体、响应体、授权方式和幂等逻辑一致。

请求头：

```http
Content-Type: application/json
tk: <loginToken>
pf: WEB
```

说明：

- `tk` 必填，取登录接口返回的 `loginToken`
- `pf` 必填，当前实现按枚举名校验，联调用 `WEB`
- `externalRequestId` 只需要放在 body 里，当前版本不强制额外 header

## 4. 请求参数

### 4.1 顶层参数

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `externalRequestId` | 是 | 外部幂等键。同一个 key 重复请求会返回同一会话。 |
| `createSession` | 是 | 复用前端创建会话的 `CreateSessionReq`。 |
| `generationOptions` | 否 | 是否同步生成候选池、初始方案、排序方案。默认全开。 |
| `returnOptions` | 否 | 返回页面地址的拼接方式。 |

### 4.2 `createSession` 核心字段

下面这些字段建议都带上，确保初始化能直接生成完整会话：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `botId` | 是 | 机器人 ID。 |
| `userName` | 否 | 学员展示名。会显示在“姓名 + 志愿规划工作台”标题里。为空时不显示。 |
| `province` | 是 | 高考省份，包含 `code/name`。 |
| `examYear` | 是 | 高考年份。 |
| `subjectType` | 是 | 选科类型，包含 `code/desc`。 |
| `subjectList` | 是 | 选科列表。 |
| `subjectScoreList` | 是 | 选科分数列表。 |
| `batch` | 是 | 批次信息，至少包含 `code/name/level`。 |
| `totalScore` | 是 | 总分。 |
| `totalScorePos` | 是 | 总分位次。 |

### 4.3 `createSession` 可选字段

这些字段按实际采集情况传，不影响接口本身的联调主链路：

`prepareType`、`sex`、`specialPlan`、`minority`、`colorBlindness`、`colorSituation`（兼容旧写法 `colorSistuation`）、`bonusPolicy`、`bonusScore`、`volunteerModel`、`volunteerDetailModel`、`preferredMajors`、`unacceptableMajors`、`preferredRegions`、`acceptForeignSchool`、`strategyType`、`tuitionRange`、`strengthSubjectList`、`height`、`visionAbility`、`ethnicity`、`politicalStatus`、`volunteerCount`、`targetType`、`filterType`

说明：

- `colorSituation` 是“色觉情况”的推荐字段名，后端兼容旧字段 `colorSistuation`。
- 常见值里会出现 `normal`，表示正常；如果不传，后端就不会记录这层色觉细项。
- `sex` 可以不传；缺失或 `code` 为空时，系统按 `{ "code": "female", "name": "女" }` 兜底。
- `strategyType` 可以不传；缺失或 `code` 为空时，系统按 `{ "code": "cautious", "name": "稳妥型" }` 兜底。
- `strategyType` 推荐使用 camelCase；如果外部系统已按 `strategy_type` 传参，后端也会兼容映射。
- 即使 `strategyType` 缺失，系统也会按目标志愿数计算冲稳保数量，不会把候选池总量当作排序方案目标数量。

### 4.4 `createSession` 完整字段说明

#### 4.4.1 基础信息

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `botId` | `Long` | 机器人 ID。 |
| `userName` | `String` | 学员展示名。会展示在详情页标题里，例如 `高翔的志愿规划工作台`。 |
| `province` | `Province` | 高考省份。 |
| `examYear` | `Integer` | 高考年份。 |
| `prepareType` | `PrepareType` | 填报类型，例如模拟填报。 |
| `subjectType` | `SubjectType` | 选科类型，例如物理、历史、综合。 |
| `subjectList` | `List<SubjectItem>` | 选科列表。 |
| `subjectScoreList` | `List<SubjectScore>` | 选科分数列表。 |
| `batch` | `Batch` | 批次信息。 |
| `totalScore` | `Integer` | 总分。 |
| `totalScorePos` | `Integer` | 总分位次。 |
| `volunteerModel` | `String` | 志愿模式，常见值为 `major`、`majorGroup`。 |
| `volunteerDetailModel` | `String` | 志愿细分模式。 |
| `volunteerCount` | `VolunteerCount` | 当前省份对应的志愿数量配置。 |
| `targetType` | `TargetType` | 目标类型，例如学校优先、专业优先、城市优先。 |
| `filterType` | `String` | 筛选模式，默认 `2`。`1`=专业不限，`2`=非负向专业，`3`=正向专业。 |

#### 4.4.2 身体和限制条件

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `specialPlan` | `Boolean` | 是否有专项计划资格。 |
| `minority` | `Boolean` | 是否少数民族。 |
| `colorBlindness` | `Boolean` | 是否色盲色弱的粗粒度开关。 |
| `colorSituation` | `List<String>` | 色觉情况。推荐值包含 `normal`、`colorBlind`、`colorWeak`。兼容旧字段名 `colorSistuation`。 |
| `bonusPolicy` | `Boolean` | 是否有加分政策。 |
| `bonusScore` | `Integer` | 加分分值。 |
| `height` | `String` | 身高。 |
| `visionAbility` | `VisionAbility` | 视力情况。 |
| `ethnicity` | `Ethnicity` | 民族信息。 |
| `politicalStatus` | `PoliticalStatus` | 政治面貌。 |
| `acceptForeignSchool` | `Boolean` | 是否接受中外合作专业。 |
| `tuitionRange` | `TuitionRange` | 学费区间。 |

#### 4.4.3 意向字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `preferredMajors` | `List<PreferredMajor>` | 正向意向专业类。 |
| `unacceptableMajors` | `List<UnacceptableMajor>` | 负向专业类。 |
| `preferredRegions` | `List<PreferredRegion>` | 正向意向省份。 |
| `strengthSubjectList` | `List<SubjectScore>` | 优势学科。 |
| `strategyType` | `StrategyType` | 志愿策略，例如激进型、稳妥型、保守型。可不传，默认稳妥型；兼容字段名 `strategy_type`。 |

#### 4.4.4 对象结构

| 对象 | 字段 | 说明 |
| --- | --- | --- |
| `Province` | `code`, `name` | 高考省份编码和名称。 |
| `Sex` | `code`, `name` | 性别编码和名称。 |
| `SubjectType` | `code`, `desc` | 选科类型编码和描述。 |
| `PrepareType` | `code`, `desc` | 填报类型编码和描述。 |
| `SubjectItem` | `isFirst`, `subjectType`, `value`, `name` | 选科列表项。 |
| `SubjectScore` | `subject`, `subjectName`, `score` | 单科成绩项。 |
| `Batch` | `code`, `name`, `score`, `level`, `pos` | 批次信息。 |
| `VolunteerCount` | `schoolCount`, `majorCount` | 志愿数量配置。 |
| `VisionAbility` | `left`, `right` | 左右眼视力。 |
| `Ethnicity` | `code`, `name` | 民族信息。 |
| `PoliticalStatus` | `code`, `name` | 政治面貌。 |
| `PreferredMajor` | `majorSubId`, `majorSubName` | 正向意向专业类。 |
| `UnacceptableMajor` | `majorId`, `majorName` | 负向专业类。 |
| `PreferredRegion` | `provinceId`, `provinceName` | 正向意向省份。 |
| `StrategyType` | `code`, `name` | 策略类型。 |
| `TuitionRange` | `min`, `max` | 学费区间。 |

### 4.5 `generationOptions` 字段说明

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `generateCandidatePool` | `Boolean` | 是否同步生成候选池。默认 `true`。 |
| `generateInitialPlan` | `Boolean` | 是否同步生成初始方案。默认 `true`。 |
| `generateOrderedPlan` | `Boolean` | 是否同步生成排序方案。默认 `true`。 |
| `forceRegenerate` | `Boolean` | 是否强制重算已有结果。默认 `false`。 |
| `returnWorkspaceState` | `Boolean` | 是否在返回值里附带工作台摘要。默认 `true`。 |

### 4.6 `returnOptions` 字段说明

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `webBaseUrl` | `String` | 前端站点基地址。用于拼接可跳转链接。为空时返回相对路径。 |
| `pathMode` | `String` | 页面路径模式。当前支持 `assistant-pc` 和 `root`，正式生产默认 `assistant-pc`。 |

## 5. 请求示例

### 5.1 简版示例

```bash
curl -X POST 'https://www.gaotuzhiyuan.com/gaotu-assistant-bot/chat/1/integration/v1/session/initialize' \
  -H 'Content-Type: application/json' \
  -H 'tk: <loginToken>' \
  -H 'pf: WEB' \
  -d '{
    "externalRequestId": "partner-20260520-0001",
    "createSession": {
      "botId": 1,
      "userName": "高翔",
      "province": { "code": "130000", "name": "河北" },
      "examYear": 2026,
      "subjectType": { "code": "WL", "desc": "物理" },
      "subjectList": [
        { "isFirst": 1, "subjectType": "first", "value": "01", "name": "物理" },
        { "isFirst": 0, "subjectType": "optional", "value": "05", "name": "化学" },
        { "isFirst": 0, "subjectType": "optional", "value": "06", "name": "生物" }
      ],
      "subjectScoreList": [
        { "subject": "01", "subjectName": "物理", "score": 85 },
        { "subject": "05", "subjectName": "化学", "score": 82 },
        { "subject": "06", "subjectName": "生物", "score": 80 }
      ],
      "batch": { "code": "B1", "name": "本科批", "level": "本科", "score": 448, "pos": 120000 },
      "totalScore": 560,
      "totalScorePos": 58000,
      "prepareType": { "code": "PREDICT", "desc": "模拟填报" },
      "specialPlan": false,
      "minority": false,
      "colorBlindness": false,
      "colorSituation": [
        "normal"
      ],
      "bonusPolicy": false,
      "bonusScore": 0,
      "preferredMajors": [
        { "majorSubId": "0201", "majorSubName": "经济学类" }
      ],
      "preferredRegions": [
        { "provinceId": "110000", "provinceName": "北京" }
      ],
      "strategyType": { "code": "cautious", "name": "稳妥型" }
    },
    "generationOptions": {
      "generateCandidatePool": true,
      "generateInitialPlan": true,
      "generateOrderedPlan": true,
      "returnWorkspaceState": true,
      "forceRegenerate": false
    },
    "returnOptions": {
      "webBaseUrl": "https://www.gaotuzhiyuan.com",
      "pathMode": "assistant-pc"
    }
  }'
```

如果外部系统已使用 snake_case，也可以把上面的 `strategyType` 写成：

```json
"strategy_type": { "code": "cautious", "name": "稳妥型" }
```

`sex` 和 `strategyType/strategy_type` 都可以省略。省略后系统分别按 `女`、`稳妥型` 兜底。

### 5.2 本地验证完整请求体

下面这份是本地联调用过的完整请求体，`createSession` 直接来自会话 `125` 的 `userScoreDetail`，只额外补了 `userName=高翔`：

```json
{
  "externalRequestId": "codex-student-name-20260520-01",
  "createSession": {
    "botId": 1,
    "userName": "高翔",
    "acceptForeignSchool": false,
    "batch": {
      "code": "17",
      "level": "01",
      "name": "第一段(批次线490分)",
      "pos": 184372,
      "score": 490
    },
    "bonusPolicy": false,
    "bonusScore": 0,
    "colorSituation": [
      "normal"
    ],
    "ethnicity": {
      "code": "02",
      "name": "蒙古族"
    },
    "examYear": 2026,
    "filterType": "2",
    "height": "165",
    "politicalStatus": {
      "code": "leagueMember",
      "name": "共青团员"
    },
    "preferredMajors": [
      {
        "majorSubId": "2",
        "majorSubName": "哲学类"
      },
      {
        "majorSubId": "10",
        "majorSubName": "政治学类"
      },
      {
        "majorSubId": "13",
        "majorSubName": "马克思主义理论类"
      },
      {
        "majorSubId": "17",
        "majorSubName": "体育学类"
      },
      {
        "majorSubId": "20",
        "majorSubName": "外国语言文学类"
      },
      {
        "majorSubId": "21",
        "majorSubName": "新闻传播学类"
      },
      {
        "majorSubId": "24",
        "majorSubName": "历史学类"
      },
      {
        "majorSubId": "83",
        "majorSubName": "中医学类"
      }
    ],
    "preferredRegions": [
      {
        "provinceId": "150000",
        "provinceName": "内蒙古"
      },
      {
        "provinceId": "110000",
        "provinceName": "北京"
      },
      {
        "provinceId": "120000",
        "provinceName": "天津"
      },
      {
        "provinceId": "140000",
        "provinceName": "山西"
      },
      {
        "provinceId": "130000",
        "provinceName": "河北"
      }
    ],
    "prepareType": {
      "code": "PREDICT",
      "desc": "模拟填报"
    },
    "province": {
      "code": "330000",
      "name": "浙江"
    },
    "sex": {
      "code": "female",
      "name": "女"
    },
    "specialPlan": false,
    "strengthSubjectList": [
      {
        "subject": "08",
        "subjectName": "语文"
      },
      {
        "subject": "02",
        "subjectName": "历史"
      }
    ],
    "strategyType": {
      "code": "cautious",
      "name": "稳妥型"
    },
    "subjectList": [
      {
        "isFirst": 0,
        "name": "历史",
        "value": "02"
      },
      {
        "isFirst": 0,
        "name": "地理",
        "value": "04"
      },
      {
        "isFirst": 0,
        "name": "技术",
        "value": "07"
      }
    ],
    "subjectScoreList": [
      {
        "score": 101,
        "subject": "08",
        "subjectName": "语文"
      },
      {
        "score": 99,
        "subject": "10",
        "subjectName": "数学"
      },
      {
        "score": 120,
        "subject": "11",
        "subjectName": "英语"
      },
      {
        "score": 70,
        "subject": "02",
        "subjectName": "历史"
      },
      {
        "score": 65,
        "subject": "04",
        "subjectName": "地理"
      },
      {
        "score": 66,
        "subject": "07",
        "subjectName": "技术"
      }
    ],
    "subjectType": {
      "code": "N",
      "desc": "综合"
    },
    "totalScore": 521,
    "totalScorePos": 148397,
    "tuitionRange": {
      "max": 60000,
      "min": 0
    },
    "unacceptableMajors": [
      {
        "majorId": "95",
        "majorName": "图书情报与档案管理类"
      },
      {
        "majorId": "85",
        "majorName": "药学类"
      }
    ],
    "visionAbility": {
      "left": "4.0",
      "right": "4.2"
    },
    "volunteerCount": {
      "majorCount": 80,
      "schoolCount": 0
    },
    "volunteerDetailModel": "OTOO",
    "volunteerModel": "major"
  },
  "generationOptions": {
    "generateCandidatePool": true,
    "generateInitialPlan": true,
    "generateOrderedPlan": true,
    "returnWorkspaceState": true,
    "forceRegenerate": false
  },
  "returnOptions": {
    "webBaseUrl": "http://localhost:3001",
    "pathMode": "assistant-pc"
  }
}
```

## 6. 响应说明

成功响应外层仍是统一 `BaseResponse`，核心字段如下：

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "chatSessionId": 1002,
    "tenantId": 1,
    "externalRequestId": "partner-20260520-0001",
    "created": true,
    "studentName": "高翔",
    "sessionUrl": "https://www.gaotuzhiyuan.com/assistant-pc/sessionDetailV2?chatSessionId=1002",
    "legacySessionUrl": "https://www.gaotuzhiyuan.com/assistant-pc/sessionDetailLegacy?chatSessionId=1002",
    "planning": {
      "phase": "ordered",
      "version": 3,
      "candidateTotal": 3266,
      "draftTotal": 80,
      "orderedTotal": 80,
      "tierCounts": {
        "冲": 24,
        "稳": 24,
        "保": 32
      }
    },
    "apis": {
      "workspaceState": "/gaotu-assistant-bot/inner/planning/1/session/workspace-state?chatSessionId=1002",
      "orderedPlan": "/gaotu-assistant-bot/inner/planning/1/session/ordered-plan?chatSessionId=1002",
      "export": "/gaotu-assistant-bot/inner/chat/1/volunteer/export?chatSessionId=1002"
    }
  }
}
```

字段说明：

- `studentName` 来自 `createSession.userName`
- `sessionUrl` 可直接打开到会话详情
- `created=false` 表示幂等命中，返回旧会话
- `legacySessionUrl` 仅用于兼容老页面

## 7. 线上联调怎么验

建议按下面顺序验证：

1. 登录接口能拿到 `loginToken`
2. 初始化接口返回 `chatSessionId`
3. 打开 `sessionUrl`，能直接进详情页
4. 详情页标题显示为 `高翔的志愿规划工作台`
5. 会话列表页能看到新会话
6. `workspaceState` 能返回方案摘要
7. `export` 能导出志愿结果

## 8. 约束和注意点

- 当前版本只认 body 里的 `externalRequestId`，不要把它当成必须 header。
- `pf` 需要传 `WEB`，不是小写 `web`。
- `userName` 只是展示名，不参与授权判断。
- 同一个 `tenantId + userId + externalRequestId` 会走幂等。
- 如果 `webBaseUrl` 为空，返回值会是相对路径。
- `generationOptions` 默认全开；如果只想拿会话，不想同步生成方案，可以按需关闭。
