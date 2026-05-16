# Gaotu User Permission Management

本文档记录高途渠道用户在 assistant 系统内的识别方式、用户 ID 获取方式，以及 3.0.1 版本可用的权限调整能力。

## 1. 用户识别链路

高途 C 端用户从授权 token 进入系统时，后端会执行：

1. 调用高途用户信息接口，根据 token 获取 `memberId`。
2. 调用高途权益接口，根据 `memberId` 获取 `userType` 和 `expirationTime`。
3. 在 `assistant_user_credential` 中按以下条件查找本地用户凭据：
   - `identifier = memberId`
   - `login_type = TOKEN`
   - `channel = gaotu`，或调用方传入的渠道值
4. 凭据表里的 `user_id` 即本系统用户 ID，对应 `assistant_user_base.id`。

高途权益到本系统等级的默认映射：

| 高途 `userType` | 本系统等级 | 说明 |
| --- | --- | --- |
| `0` | `SUPER_VIP` | 白名单/超级权限 |
| `1` | `VIP` | 普通付费 VIP |
| `2` 或空值 | `ORIGIN` | 未购买或未知 |

3.0.1 起，普通 `VIP` 用户的默认建会话上限调整为 `500`。该上限会在用户登录同步权益、后台同步权益或后台手动调整等级时写入用户 `limitSettings.createSessionLimit`。

## 2. 获取用户 ID

推荐使用后台管理接口按高途 `memberId` 查询：

```bash
curl -X GET \
  "https://www.gaotuzhiyuan.com/gaotu-assistant-bot/admin/user/gaotu-user?memberId={memberId}&channel=gaotu"
```

返回的 `id` 字段就是本系统用户 ID。返回中的 `userLevel`、`expiredDate`、`limitSettingsOb.createSessionLimit` 可用于确认当前权限状态。

也可以直接查库定位：

```sql
select user_id, identifier, login_type, channel
from assistant_user_credential
where identifier = '{memberId}'
  and login_type = 'TOKEN'
  and channel = 'gaotu';
```

## 3. 调整高途用户权限

### 3.1 按 memberId 手动设置等级

```bash
curl -X POST \
  "https://www.gaotuzhiyuan.com/gaotu-assistant-bot/admin/user/update-gaotu-user-level?memberId={memberId}&channel=gaotu&userLevel=SUPER_VIP&expiredDate=2026-12-31"
```

参数说明：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `memberId` | 是 | 高途用户 ID，来自 token 登录链路 |
| `channel` | 否 | 默认 `gaotu`；B 端用户可能是带 `4b` 后缀的渠道 |
| `userLevel` | 是 | `SUPER_VIP`、`VIP`、`ORIGIN` |
| `expiredDate` | 否 | 格式 `yyyy-MM-dd`；不传时按用户等级默认有效期顺延 |

### 3.2 按 memberId 同步高途权益

```bash
curl -X POST \
  "https://www.gaotuzhiyuan.com/gaotu-assistant-bot/admin/user/fix-gaotu-user-level?memberId={memberId}&channel=gaotu"
```

该接口会重新调用高途权益接口，根据 `userType` 映射本系统等级并更新过期时间。

### 3.3 按本系统 userId 设置等级

旧接口仍可使用：

```bash
curl -X POST \
  "https://www.gaotuzhiyuan.com/gaotu-assistant-bot/admin/user/update-user-level?userId={userId}&channel=gaotu&userLevel=SUPER_VIP&expiredDate=2026-12-31"
```

如果已知本系统 `userId`，该接口可直接调整；如果只知道高途用户，优先使用按 `memberId` 的接口，减少查库步骤。

## 4. 运维注意事项

- `/admin/**` 当前不经过普通登录拦截器，生产环境必须通过内网、Nginx allowlist、运维跳板或其他外层机制限制访问。
- 手动调整权限会覆盖当前用户等级、过期时间和默认限制配置；如果后续用户再次通过高途 token 登录，系统会按高途权益重新同步等级。
- 当前建会话限制仍是总量限制，不是按天限制，也未按模拟填报/智能填报拆分。

## 5. TODO

- 高考出分后，智能填报场景需要进一步调整为每天最多创建 2 个会话；模拟填报普通用户每天 10 个会话。本版本只记录该需求，不改当前权限校验模型。
