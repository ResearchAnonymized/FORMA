"""Input errors returned by the public functions."""


class InputError(Exception):
    def __init__(self, detail: str, code: str = "invalid_input") -> None:
        super().__init__(detail)
        self.detail = detail
        self.code = code

    def as_dict(self) -> dict:
        body = {"ok": False, "error": {"code": self.code, "detail": self.detail}}
        if self.code == "type_error":
            body["excluded_from_decision_metrics"] = True
        return body


class TypeCheckError(InputError):
    """A comparison was given a value of the wrong type. Excluded from decision metrics."""

    def __init__(self, detail: str = "le compares numbers") -> None:
        super().__init__(detail, code="type_error")


class HiddenValueAccess(Exception):
    """The classifier tried to read a raw value it is not allowed to see."""

    def __init__(self, attribute_id: str) -> None:
        super().__init__(attribute_id)
        self.attribute_id = attribute_id
