# release-3.0.2 hotfix: volunteer rights mode

## 背景

高考出分后，主站会切入真实智能填报（`prepareType=VOLUNTEER`）数据。当前 3.0.2 版本的权益模型仍然只按用户等级（`SUPER_VIP / VIP / ORIGIN`）和总量限制判断，不区分“模拟填报 / 智能填报”阶段。

为了在不改库、不批量改用户等级的前提下快速收口，补充一个全局配置型 hotfix。

## hotfix 目标

增加一个全局开关：

- 配置关闭：沿用现有权限模型
- 配置开启：所有非 `SUPER_VIP` 用户在关键能力上统一受限

当前限制点：

- `CreateSession`
- `ModifyScore`
- `DoChat`

返回统一提示：

- `当前处于智能填报权益管控期，仅SUPER_VIP用户可使用该功能`

## 配置项

位置：`gaotu.zhiyuan.volunteer-super-vip-only`

示例：

```yaml
gaotu:
  zhiyuan:
    volunteer-super-vip-only: true
```

## 代码变更点

1. `GaotuProperties`

新增字段：

- `volunteerSuperVipOnly`

2. `UserBizService.checkRights(...)`

在原有白名单、过期校验、次数校验之前增加全局判断：

- 如果开关开启，且用户等级不是 `SUPER_VIP`
- 直接返回 `canOperate=false`

这样不会改动数据库中的 `userLevel / expiredDate / limitSettings`，也不会影响高途 token 登录同步逻辑。

## 为什么不直接改库

当前高途用户登录链路中，每次 token 登录都会重新调用高途权益接口，并同步本地等级：

- `userType=0 -> SUPER_VIP`
- `userType=1 -> VIP`
- `userType=2/null -> ORIGIN`

如果直接批量改库：

- 后续用户再次登录后，等级仍可能被高途权益重新覆盖
- 运维回滚成本高
- 无法表达“阶段性策略”

因此 hotfix 采用运行时配置开关方式。

## 当前限制与后续 TODO

当前 hotfix 是“全局限制”，并不区分 `prepareType=PREDICT` 还是 `VOLUNTEER`。

如果后续要做更精细的策略，需要继续演进：

1. 在 `check-rights` 链路中显式传 `prepareType`
2. 只对 `VOLUNTEER` 场景限制非 `SUPER_VIP`
3. 将总量限制演进为按天限制

当前版本不包含这些增强，仅提供快速可回滚的 3.0.2 补充 hotfix。
