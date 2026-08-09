from collections.abc import Generator
from typing import TypeVar

T = TypeVar("T")


def batch_items(
    items: list[T],
    batch_size: int,
) -> Generator[list[T], None, None]:
    """
    Yield items in fixed-size batches.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than 0")

    for index in range(0, len(items), batch_size):
        yield items[index : index + batch_size]
