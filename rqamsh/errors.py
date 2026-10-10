"""Harness 的结构化异常。"""


class HarnessError(Exception):
    """保存错误码、HTTP 状态及可供 Agent 处理的诊断。"""

    def __init__(self, code, message, *, status=None, details=None):
        """初始化错误；details 保留任务或批量导入的完整结果。"""
        super().__init__(message)
        self.code = code
        self.status = status
        self.details = details

    def to_dict(self):
        """返回可 JSON 序列化的错误对象。"""
        return {"error": self.code, "message": str(self), "status": self.status, "details": self.details}
