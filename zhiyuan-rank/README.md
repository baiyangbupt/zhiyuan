# zhiyuan-rank

智愿 AI 志愿填报系统排序推荐服务，基于 Flask。

无状态计算服务，接收学生信息和志愿列表，返回排序后的推荐结果。

## 技术栈

- Python 3.10 + Flask 2.3
- Pandas + NumPy (计算引擎)
- Gunicorn (生产 WSGI)

## 开发

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py   # 端口 5001
```

## API

| Method | Path | 说明 |
|--------|------|------|
| POST | `/gaokao-volunteer-rank/recommend_submajor` | 专业类推荐 |
| POST | `/gaokao-volunteer-rank/recommend_volunteer` | 志愿排序 |
| POST | `/gaokao-volunteer-rank/query_weight` | 权重查询 |
| GET | `/health` | 健康检查 |

## 数据

启动时加载 `services/data/` 和 `services/dict/` 下的静态数据文件（JSON + Excel）到内存。

## Docker 部署

```bash
./build-docker-fast.sh <env> <version>   # 构建并推送
./run-docker.sh <env> <version>          # 拉取并运行 (宿主端口 8092 → 容器 5001)
```

## 生产运行

```bash
gunicorn -w 4 -b 0.0.0.0:5001 app:app
```
