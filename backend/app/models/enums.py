import enum


class TrafficLight(str, enum.Enum):
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"


class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    FETCHING = "FETCHING"
    EXTRACTING = "EXTRACTING"
    PARSING = "PARSING"
    ANALYSING = "ANALYSING"
    GENERATING = "GENERATING"
    DELIVERING = "DELIVERING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class DeliveryStatus(str, enum.Enum):
    PENDING = "PENDING"
    PUSHED = "PUSHED"
    ERROR = "ERROR"


class AccountType(str, enum.Enum):
    CREDIT_CARD = "CREDIT_CARD"
    PERSONAL_LOAN = "PERSONAL_LOAN"
    PAYDAY_LOAN = "PAYDAY_LOAN"
    OVERDRAFT = "OVERDRAFT"
    MORTGAGE = "MORTGAGE"
    HIRE_PURCHASE = "HIRE_PURCHASE"
    STORE_CARD = "STORE_CARD"
    OTHER = "OTHER"
