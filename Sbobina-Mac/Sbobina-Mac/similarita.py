"""Somiglianza tra testi: embeddings (se disponibili) oppure confronto lessicale TF-IDF."""
import math
import re
import unicodedata
from collections import Counter


def _norm(t: str) -> str:
    return unicodedata.normalize("NFKD", t.lower()).encode("ascii", "ignore").decode()


_STOP = {_norm(w) for w in """che con per una uno gli delle dei del della dello degli sono come anche non
più quindi quando dove questo questa questi queste quello quella cosa cose essere stato stata hanno alla
alle allo agli nella nelle nello negli sulla sulle suo sua suoi loro dalla dalle molto così poi ecco
allora ogni tutto tutti tutte altro altri altre fatto fanno viene vengono può possono dopo prima""".split()}


def tokens(t: str) -> list:
    return [w[:6] for w in re.findall(r"[a-z0-9]{4,}", _norm(t)) if w not in _STOP]


def matrice_lessicale(queries, docs):
    tq = [Counter(tokens(q)) for q in queries]
    td = [Counter(tokens(d)) for d in docs]
    df = Counter()
    for c in tq + td:
        df.update(c.keys())
    N = len(tq) + len(td)
    idf = {w: math.log((N + 1) / (n + 1)) + 1 for w, n in df.items()}

    def vec(c):
        v = {w: (1 + math.log(n)) * idf[w] for w, n in c.items()}
        nrm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {w: x / nrm for w, x in v.items()}

    vq, vd = [vec(c) for c in tq], [vec(c) for c in td]
    return [[sum(x * d.get(w, 0.0) for w, x in q.items()) for d in vd] for q in vq]


def _coseno(a, b):
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


class Similarita:
    SOGLIA_EMBEDDING = 0.50
    SOGLIA_LESSICALE = 0.10

    def __init__(self, llm=None):
        self.llm = llm
        self.usa_embedding = bool(llm is not None and getattr(llm, "embed_ok", False))
        self.metodo = "lessicale"

    @property
    def soglia(self):
        return self.SOGLIA_EMBEDDING if self.metodo == "embedding" else self.SOGLIA_LESSICALE

    def matrice(self, queries, docs):
        if not queries or not docs:
            return [[0.0] * len(docs) for _ in queries]
        if self.usa_embedding:
            try:
                eq = self.llm.embed(queries)
                ed = self.llm.embed(docs)
                self.metodo = "embedding"
                return [[_coseno(q, d) for d in ed] for q in eq]
            except Exception:
                self.usa_embedding = False
        self.metodo = "lessicale"
        return matrice_lessicale(queries, docs)
