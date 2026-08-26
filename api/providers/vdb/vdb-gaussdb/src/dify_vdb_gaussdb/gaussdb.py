import json
import uuid
from contextlib import contextmanager
from typing import Any, override

import psycopg2.extras
import psycopg2.pool
from pydantic import BaseModel, model_validator

from configs import dify_config
from core.rag.datasource.vdb.vector_base import BaseVector
from core.rag.datasource.vdb.vector_factory import AbstractVectorFactory
from core.rag.datasource.vdb.vector_type import VectorType
from core.rag.embedding.embedding_base import Embeddings
from core.rag.models.document import Document
from extensions.ext_redis import redis_client
from models.dataset import Dataset


class GaussDBConfig(BaseModel):
    host: str
    port: int
    user: str
    password: str
    database: str
    min_connection: int
    max_connection: int
    index_type: str = "ivfflat"  # ivfflat / diskann

    @model_validator(mode="before")
    @classmethod
    def validate_config(cls, values: dict[str, Any]):
        if not values["host"]:
            raise ValueError("config GAUSSDB_HOST is required")
        if not values["port"]:
            raise ValueError("config GAUSSDB_PORT is required")
        if not values["user"]:
            raise ValueError("config GAUSSDB_USER is required")
        if not values["password"]:
            raise ValueError("config GAUSSDB_PASSWORD is required")
        if not values["database"]:
            raise ValueError("config GAUSSDB_DATABASE is required")
        if values["min_connection"] > values["max_connection"]:
            raise ValueError("GAUSSDB_MIN_CONNECTION should be <= GAUSSDB_MAX_CONNECTION")
        if values.get("index_type") not in ("ivfflat", "diskann"):
            raise ValueError("GAUSSDB_INDEX_TYPE must be 'ivfflat' or 'diskann'")
        return values


SQL_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS {table_name} (
    id UUID PRIMARY KEY,
    text TEXT NOT NULL,
    meta JSONB NOT NULL,
    embedding floatvector({dimension}) NOT NULL
);
"""

# GsIVFFLAT（≤1024 维，小数据 1万~200万）
SQL_CREATE_INDEX_IVFFLAT = """
CREATE INDEX IF NOT EXISTS embedding_cosine_{table_name}_idx ON {table_name}
USING GSIVFFLAT(embedding cosine) WITH (IVF_NLIST = 256);
"""

# GsDiskANN（大数据；>1024 维必须 +PQ，由 _build_diskann_sql 动态生成）
SQL_CREATE_INDEX_DISKANN = """
CREATE INDEX IF NOT EXISTS embedding_cosine_{table_name}_idx ON {table_name}
USING GsDiskANN(embedding cosine) WITH (pq_nseg={pq_nseg}, pq_nclus=16, enable_pq={enable_pq}, subgraph_count={subgraph_count}, enable_vector_copy={enable_vector_copy});
"""

# GsDiskANN 降级模板（505 等旧版本不支持 enable_vector_copy 参数）
SQL_CREATE_INDEX_DISKANN_NO_VC = """
CREATE INDEX IF NOT EXISTS embedding_cosine_{table_name}_idx ON {table_name}
USING GsDiskANN(embedding cosine) WITH (pq_nseg={pq_nseg}, pq_nclus=16, enable_pq={enable_pq}, subgraph_count={subgraph_count});
"""

# BM25 全文索引（优先方案；若创建失败降级 tsvector）
SQL_CREATE_BM25_INDEX = """
CREATE INDEX IF NOT EXISTS text_bm25_{table_name}_idx ON {table_name} USING BM25(text);
"""


class GaussDB(BaseVector):
    def __init__(self, collection_name: str, config: GaussDBConfig):
        super().__init__(collection_name)
        self.pool = self._create_connection_pool(config)
        self.table_name = f"embedding_{collection_name}"
        self.index_type = config.index_type

    @override
    def get_type(self) -> str:
        return VectorType.GAUSSDB

    def _create_connection_pool(self, config: GaussDBConfig):
        return psycopg2.pool.SimpleConnectionPool(
            config.min_connection, config.max_connection,
            host=config.host, port=config.port, user=config.user,
            password=config.password, database=config.database,
        )

    @contextmanager
    def _get_cursor(self):
        conn = self.pool.getconn()
        cur = conn.cursor()
        try:
            yield cur
        finally:
            cur.close()
            conn.commit()
            self.pool.putconn(conn)

    def _calc_pq_nseg(self, dimension: int) -> int:
        """按 chm 规则算 pq_nseg（须整除维度）。"""
        if dimension <= 512:
            return dimension
        elif dimension <= 1024:
            return dimension // 2
        else:
            # >1024：取能整除的合适值，优先 /8 或 /16
            for divisor in (8, 16, 24, 32, 48, 96):
                if dimension % divisor == 0:
                    return dimension // divisor
            return dimension // 8  # 兜底

    @override
    def create(self, texts: list[Document], embeddings: list[list[float]], **kwargs):
        dimension = len(embeddings[0])
        if dimension > 4096:
            raise ValueError(f"维度 {dimension} 超过 GaussDB 上限 4096")
        if dimension > 1024 and self.index_type != "diskann":
            raise ValueError(f"维度 {dimension}>1024 必须 GAUSSDB_INDEX_TYPE=diskann（GsIVFFLAT 上限 1024）")
        self._create_collection(dimension)
        self.add_texts(texts, embeddings)
        self._create_index(dimension)

    def _create_index(self, dimension: int):
        index_cache_key = f"vector_index_{self._collection_name}"
        lock_name = f"{index_cache_key}_lock"
        with redis_client.lock(lock_name, timeout=60):
            if redis_client.get(index_cache_key):
                return
            with self._get_cursor() as cur:
                if self.index_type == "ivfflat":
                    cur.execute(SQL_CREATE_INDEX_IVFFLAT.format(table_name=self.table_name))
                    cur.execute("SET gsivfflat_probes = 25")
                else:  # diskann
                    pq_nseg = self._calc_pq_nseg(dimension)
                    enable_pq = "true" if dimension > 1024 else "false"
                    subgraph_count = 1 if dimension > 1024 else 0
                    enable_vector_copy = "false" if dimension > 1024 else "true"
                    # GsDiskANN 建索引需较大内存（默认 64MB 不够，L20 实测）
                    cur.execute("SET maintenance_work_mem = '512MB'")
                    try:
                        cur.execute(SQL_CREATE_INDEX_DISKANN.format(
                            table_name=self.table_name, pq_nseg=pq_nseg,
                            enable_pq=enable_pq, subgraph_count=subgraph_count,
                            enable_vector_copy=enable_vector_copy,
                        ))
                    except Exception as e:
                        if "enable_vector_copy" in str(e):
                            # 505 等旧版本不支持 enable_vector_copy，回滚后降级重试
                            cur.connection.rollback()
                            cur.execute(SQL_CREATE_INDEX_DISKANN_NO_VC.format(
                                table_name=self.table_name, pq_nseg=pq_nseg,
                                enable_pq=enable_pq, subgraph_count=subgraph_count,
                            ))
                        else:
                            raise
                # BM25 全文索引（失败则降级，不影响主流程）
                try:
                    cur.execute(SQL_CREATE_BM25_INDEX.format(table_name=self.table_name))
                except Exception:
                    pass  # BM25 不支持则降级 tsvector（search_by_full_text 内处理）
            redis_client.set(index_cache_key, 1, ex=3600)

    @override
    def add_texts(self, documents: list[Document], embeddings: list[list[float]], **kwargs):
        values = []
        pks = []
        for i, doc in enumerate(documents):
            doc_id = doc.metadata.get("doc_id", str(uuid.uuid4())) if doc.metadata else str(uuid.uuid4())
            pks.append(doc_id)
            values.append((doc_id, doc.page_content, json.dumps(doc.metadata), str(embeddings[i])))
        with self._get_cursor() as cur:
            psycopg2.extras.execute_values(
                cur, f"INSERT INTO {self.table_name} (id, text, meta, embedding) VALUES %s", values
            )
        return pks

    @override
    def text_exists(self, id: str) -> bool:
        with self._get_cursor() as cur:
            cur.execute(f"SELECT id FROM {self.table_name} WHERE id = %s", (id,))
            return cur.fetchone() is not None

    def get_by_ids(self, ids: list[str]) -> list[Document]:
        with self._get_cursor() as cur:
            cur.execute(f"SELECT meta, text FROM {self.table_name} WHERE id IN %s", (tuple(ids),))
            return [Document(page_content=r[1], metadata=r[0]) for r in cur]

    @override
    def delete_by_ids(self, ids: list[str]):
        if not ids:
            return
        with self._get_cursor() as cur:
            cur.execute(f"DELETE FROM {self.table_name} WHERE id IN %s", (tuple(ids),))

    @override
    def delete_by_metadata_field(self, key: str, value: str):
        with self._get_cursor() as cur:
            cur.execute(f"DELETE FROM {self.table_name} WHERE meta->>%s = %s", (key, value))

    @override
    def search_by_vector(self, query_vector: list[float], **kwargs: Any) -> list[Document]:
        top_k = kwargs.get("top_k", 4)
        if not isinstance(top_k, int) or top_k <= 0:
            raise ValueError("top_k must be a positive integer")
        vec = str(query_vector)
        with self._get_cursor() as cur:
            if self.index_type == "ivfflat":
                cur.execute("SET gsivfflat_probes = 25")
            cur.execute(
                f"SELECT meta, text, embedding <+> %s AS distance FROM {self.table_name}"
                f" ORDER BY distance LIMIT {top_k}",
                (vec,),
            )
            docs = []
            score_threshold = float(kwargs.get("score_threshold") or 0.0)
            for metadata, text, distance in cur:
                score = 1 - distance
                metadata["score"] = score
                if score >= score_threshold:
                    docs.append(Document(page_content=text, metadata=metadata))
        return docs

    @override
    def search_by_full_text(self, query: str, **kwargs: Any) -> list[Document]:
        top_k = kwargs.get("top_k", 5)
        if not isinstance(top_k, int) or top_k <= 0:
            raise ValueError("top_k must be a positive integer")
        with self._get_cursor() as cur:
            # 优先 BM25；失败降级 tsvector
            try:
                cur.execute("SET bm25_ranking_metric = 0")
                cur.execute(
                    f"SELECT /*+ indexscan({self.table_name} text_bm25_{self.table_name}_idx) */"
                    f" meta, text, text ### %s AS score FROM {self.table_name}"
                    f" ORDER BY score DESC LIMIT {top_k}",
                    (query,),
                )
                rows = cur.fetchall()
            except Exception:
                # 降级 tsvector（G9 实测可用）
                cur.execute(
                    f"SELECT meta, text, ts_rank(to_tsvector(coalesce(text, '')), plainto_tsquery(%s)) AS score"
                    f" FROM {self.table_name}"
                    f" WHERE to_tsvector(text) @@ plainto_tsquery(%s)"
                    f" ORDER BY score DESC LIMIT {top_k}",
                    (f"'{query}'", f"'{query}'"),
                )
                rows = cur.fetchall()
            docs = []
            for metadata, text, score in rows:
                metadata["score"] = score
                docs.append(Document(page_content=text, metadata=metadata))
        return docs

    @override
    def delete(self):
        with self._get_cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {self.table_name}")

    def _create_collection(self, dimension: int):
        cache_key = f"vector_indexing_{self._collection_name}"
        lock_name = f"{cache_key}_lock"
        with redis_client.lock(lock_name, timeout=20):
            if redis_client.get(cache_key):
                return
            with self._get_cursor() as cur:
                cur.execute(SQL_CREATE_TABLE.format(table_name=self.table_name, dimension=dimension))
            redis_client.set(cache_key, 1, ex=3600)


class GaussDBFactory(AbstractVectorFactory):
    @override
    def init_vector(self, dataset: Dataset, attributes: list, embeddings: Embeddings) -> GaussDB:
        if dataset.index_struct_dict:
            collection_name = dataset.index_struct_dict["vector_store"]["class_prefix"]
        else:
            dataset_id = dataset.id
            collection_name = Dataset.genCollection_name_by_id(dataset_id)
            dataset.index_struct = json.dumps(self.gen_index_struct_dict(VectorType.GAUSSDB, collection_name))
        return GaussDB(
            collection_name=collection_name,
            config=GaussDBConfig(
                host=dify_config.GAUSSDB_HOST or "localhost",
                port=dify_config.GAUSSDB_PORT,
                user=dify_config.GAUSSDB_USER or "postgres",
                password=dify_config.GAUSSDB_PASSWORD or "",
                database=dify_config.GAUSSDB_DATABASE or "dify",
                min_connection=dify_config.GAUSSDB_MIN_CONNECTION,
                max_connection=dify_config.GAUSSDB_MAX_CONNECTION,
                index_type=dify_config.GAUSSDB_INDEX_TYPE or "ivfflat",
            ),
        )
