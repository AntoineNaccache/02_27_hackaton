from processors.fr import FrenchProcessor
from processors.en import EnglishProcessor

_REGISTRY = {
    "fr": FrenchProcessor,
    "en": EnglishProcessor,
}


def get_processor(language: str):
    """Return the appropriate processor instance for a given language code."""
    processor_cls = _REGISTRY.get(language)
    if processor_cls is None:
        raise ValueError(f"No processor registered for language '{language}'")
    return processor_cls()
