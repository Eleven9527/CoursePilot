from enum import StrEnum


class ParseStepStatus(StrEnum):
    """解析任务和步骤的统一状态定义，与数据库中保存的字符串值保持一致。"""

    QUEUED = "queued"  # 等待执行
    SOURCE_SAVED = "source_saved"  # 原始文件已保存，等待开始解析
    SOURCE_SAVE_FAILED = "source_save_failed"  # 原始文件读取或保存失败
    PROCESSING = "processing"  # 正在执行
    MINERU_PARSING = "mineru_parsing"  # 正在执行 MinerU 结构解析
    MINERU_FAILED = "mineru_failed"  # MinerU 结构解析失败
    CHUNKING = "chunking"  # 正在生成文本切分块
    CHUNKING_FAILED = "chunking_failed"  # 文本切分失败
    SUCCEEDED = "succeeded"  # 执行成功
    FAILED = "failed"  # 执行失败
