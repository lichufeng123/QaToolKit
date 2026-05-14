from __future__ import annotations

import random
import string
import uuid
from datetime import datetime, timedelta


class Faker:
    def boolean(self) -> bool:
        return bool(random.getrandbits(1))

    def random_int(self, min: int = 0, max: int = 1000) -> int:
        return random.randint(min, max)

    def random_element(self, elements):
        return random.choice(list(elements))

    def email(self) -> str:
        return f"user{random.randint(1000, 9999)}@example.com"

    def date(self) -> datetime.date:
        return (datetime.utcnow() - timedelta(days=random.randint(0, 3650))).date()

    def date_time(self) -> datetime:
        return datetime.utcnow() - timedelta(seconds=random.randint(0, 31536000))

    def url(self) -> str:
        return f"https://example.com/{uuid.uuid4().hex[:8]}"

    def password(self, length: int = 12) -> str:
        chars = string.ascii_letters + string.digits + "!@#$%*"
        return "".join(random.choice(chars) for _ in range(length))

    def text(self, max_nb_chars: int = 200) -> str:
        words = ["test", "data", "sample", "value", "alpha", "beta", "gamma"]
        text = " ".join(random.choice(words) for _ in range(max(1, max_nb_chars // 5)))
        return text[:max_nb_chars]
