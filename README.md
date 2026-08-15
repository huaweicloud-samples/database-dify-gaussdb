# dify-gaussdb

[![Status](https://img.shields.io/badge/Status-Incubating-blue)]()
[![Huawei Cloud](https://img.shields.io/badge/Huawei%20Cloud-Samples-red)]()
[![Dify](https://img.shields.io/badge/Dify-1.16.1-blue)]()
[![GaussDB](https://img.shields.io/badge/GaussDB-O模式-orange)]()

GaussDB 生态建设：Dify 适配兼容 GaussDB（关系库 + 向量库）。

## Overview

本项目将 [Dify](https://github.com/langgenius/dify) 1.16.1 适配到华为云 GaussDB，支持：

- **关系库**：GaussDB O模式（DBCOMPATIBILITY='A'），通过 `opengauss+psycopg2` 方言连接，集中式/分布式统一支持
- **向量库**：GaussDB 原生向量（floatvector + GsIVFFLAT/GsDiskANN 索引），支持 cosine 相似度检索
- **完整适配**：88 个数据库迁移、Model 层空串→NULL 补丁、向量库 adapter（create/add/search/delete 全链路）

## 镜像下载

预构建镜像（1.4GB，含全部适配 + 437 依赖包）从 [Release v1.16.1-gaussdb](https://github.com/huaweicloud-samples/database-dify-gaussdb/releases/tag/v1.16.1-gaussdb) 下载：

```bash
docker load -i dify-api-gaussdb-1.16.1.tar
```

## 快速部署

**部署目录结构**（`.env` 必须和 `docker-compose.yaml` 在同一目录）：

```
/opt/dify-gaussdb/                  ← 部署目录
├── docker-compose.yaml             ← 从 delivery/ 复制
├── .env                            ← 从 delivery/.env.gaussdb.example 复制并修改
├── dify-api-gaussdb-1.16.1.tar     ← 镜像（docker load 后可删）
└── tests/                          ← 测试脚本（从 delivery/tests/ 复制，可选）
```

```bash
# 1. 准备部署目录
mkdir -p /opt/dify-gaussdb && cd /opt/dify-gaussdb

# 2. 下载镜像 tar 并加载（从 Release 下载 tar 到本目录）
docker load -i dify-api-gaussdb-1.16.1.tar

# 3. 从交付包复制 compose 和配置模板（delivery/ 内容已随仓库 clone 到本地）
cp delivery/docker-compose.yaml ./
cp delivery/.env.gaussdb.example .env

# 4. 编辑 .env，填入 GaussDB 连接信息（DB_HOST/PORT/USERNAME/PASSWORD 等）
vi .env

# 5. 启动
docker compose up -d
```

详细步骤见 [delivery/实施部署交付文档.md](delivery/实施部署交付文档.md)。

## 测试

测试方法见 [delivery/测试指南.md](delivery/测试指南.md)，含 5 层测试：
- L1 健康检查
- L2 连库 + 迁移验证
- L3 关系库 CRUD 端到端（HTTP API）
- L4 向量库 CRUD（IVFFLAT / DiskANN / DiskANN+PQ）
- L5 GaussDB 侧数据一致性验证

测试脚本在 [delivery/tests/](delivery/tests/)（自动从 .env 读配置，无需手改）。

## 适配改造说明

### 关系库适配
- `DB_TYPE=gaussdb` → `opengauss+psycopg2` 方言（opengauss-sqlalchemy 2.4.0）
- O模式空串→NULL 补丁：`api/extensions/ext_database.py` 的 `before_cursor_execute` 事件，把空串转空格
- inspector 补丁：用 information_schema.columns 替代 pg_catalog
- 88 个迁移的 `_is_pg` 判断在 opengauss 方言下走 else 分支

### 向量库适配
- adapter：`api/providers/vdb/vdb-gaussdb/`（dify-vdb-gaussdb）
- 索引：GsIVFFLAT（≤1024维）/ GsDiskANN（>1024维自动 PQ 降维，集中式≤4096）
- 距离：cosine `<+>`，score = 1 - distance
- 全文检索：BM25 索引优先，失败降级 tsvector

### 维度限制

| 索引类型 | 集中式 | 分布式 |
|---|---|---|
| GsIVFFLAT | ≤1024 维 | ≤1024 维 |
| GsDiskANN（无PQ） | ≤1024 维 | ≤1024 维 |
| GsDiskANN+PQ | ≤4096 维 | ≤1024 维（硬限） |

## 目录结构

```
├── api/                    # Dify API 源码（含 GaussDB 适配改造）
│   ├── extensions/ext_database.py    # O模式 patch（空串/inspector）
│   ├── configs/middleware/           # DB_TYPE=gaussdb 配置
│   ├── providers/vdb/vdb-gaussdb/    # 向量库 adapter
│   ├── migrations/versions/          # 88 迁移（5 个空串修补）
│   └── Dockerfile / Dockerfile.production  # 镜像构建
├── delivery/               # 交付包
│   ├── dify-api-gaussdb-1.16.1.tar   # 镜像（Release 下载，不放 git）
│   ├── docker-compose.yaml           # 已替换镜像的 compose
│   ├── .env.gaussdb.example          # GaussDB 配置模板
│   ├── 实施部署交付文档.md
│   ├── 测试指南.md
│   └── tests/                        # 测试脚本（从 .env 读配置）
├── flask-restx-wheel/      # flask-restx 本地 wheel（Dockerfile 引用）
└── docker/                 # Dify docker compose 配置
```

## License

本项目基于 [Dify](https://github.com/langgenius/dify)（Apache-2.0）改编。
