-- 版本登记的粒度从「每个来源一行」改成「每个来源 × 每组查询参数一行」。
--
-- 为什么必须改：版本值现在是响应内容的摘要，内容天然按参数分——不同参数的查询
-- 当然是不同内容。继续按 source_system 单行登记，等于让所有参数共用一个格子，
-- 后一次查询必然挤掉前一次，于是所有旧证据立刻变成 stale，失效判定退化成永久 fail-closed。
--
-- 为什么旧数据可以直接丢：这张表只是「最近一次观测到的版本」的缓存，不是事实来源，
-- 任何一行都能由下一次取数整行重建。而且旧键 (source_system) 没有 params_digest，
-- 无法归属到任何一个具体查询——保留它只会与新键的第一条记录并存成一条永远比不中的无主行。
DROP TABLE IF EXISTS evidence_source_version;

CREATE TABLE IF NOT EXISTS evidence_source_version
(
    source_system VARCHAR(64) NOT NULL COMMENT '取数来源',
    params_digest CHAR(32)    NOT NULL COMMENT '查询参数规范化后的 SHA-256 前 32 位十六进制；版本按查询参数分别登记',
    data_version  VARCHAR(64) NOT NULL COMMENT '最近一次观察到的版本：该次响应 data 的内容摘要',
    observed_at   DATETIME    NOT NULL COMMENT '最近一次观察到该版本的时间',
    updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (source_system, params_digest)
);
