from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

PREFIXES = {
    "intfloat/multilingual-e5": ("query: ", "passage: "),
    "intfloat/e5": ("query: ", "passage: "),
    "google/embeddinggemma": (
        "task: search result | query: ",
        "task: search result | title: none | text: ",
    ),
}
DEFAULT_PREFIXES = ("", "")

_model = None


def prefixes() -> tuple[str, str]:
    for name, pair in PREFIXES.items():
        if settings.embed_model.startswith(name):
            return pair
    log.warning("embed_prefixes_unknown", model=settings.embed_model)
    return DEFAULT_PREFIXES


def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        log.info(
            "embed_model_loading", model=settings.embed_model, device=settings.embed_device
        )
        _model = SentenceTransformer(settings.embed_model, device=settings.embed_device)
    return _model


def embed_query(text: str) -> list[float]:
    query_prefix, _ = prefixes()
    return get_model().encode(query_prefix + text, normalize_embeddings=True).tolist()


def embed_documents(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    if not texts:
        return []
    _, doc_prefix = prefixes()
    vectors = get_model().encode(
        [doc_prefix + text for text in texts],
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return vectors.tolist()
