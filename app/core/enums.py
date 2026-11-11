from enum import StrEnum


class DocumentStatus(StrEnum):
    """单个文档在串行处理流程中的当前状态。"""

    SOURCE_SAVED = "source_saved"
    MINERU_PARSING = "mineru_parsing"
    MINERU_PARSED = "mineru_parsed"
    MINERU_FAILED = "mineru_failed"
    CHUNKING = "chunking"
    CHUNKING_FAILED = "chunking_failed"
    SUCCEEDED = "succeeded"
