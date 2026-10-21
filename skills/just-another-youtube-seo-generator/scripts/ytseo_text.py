"""Общие функции текста для research.py и validate.py: токены, «основы» слов, плоская форма для хештегов."""
import re

STOP_RU = set("""и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее мне было вот от меня
еще нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был него до вас нибудь опять уж вам ведь там потом себя
ничего ей может они тут где есть надо ней для мы тебя их чем была сам чтоб без будто чего раз тоже себе под будет ж тогда кто
этот того потому этого какой совсем ним здесь этом один почти мой тем чтобы нее сейчас были куда зачем всех никогда можно при
два об другой хоть после над больше тот через эти нас про всего них какая много разве три эту моя свою этой перед иногда лучше
чуть том нельзя такой им более всегда конечно всю между это""".split())
STOP_EN = set("a an the and or of to in on for with is are was be it this that these those your you i my we our at by from as "
              "how what why when where which who vs".split())
STOP = STOP_RU | STOP_EN


def tokens(s: str) -> list[str]:
    return re.findall(r"[0-9a-zа-я]+", s.lower().replace("ё", "е"))


def stem(w: str) -> str:
    """Грубая основа: режет окончание, чтобы «хештеги» и «хештег», «студио» и «студии» совпадали. Это эвристика, не морфология."""
    if w.isdigit() or len(w) <= 4:
        return w
    if re.search(r"[а-я]", w):
        return w[: max(4, len(w) - 2)]
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def stems(s: str) -> list[str]:
    return [stem(t) for t in tokens(s)]


def flat(s: str) -> str:
    """Плоская форма: «FL Studio 26» и «#flstudio26» дают одно и то же."""
    return re.sub(r"[^0-9a-zа-я]", "", s.lower().replace("ё", "е"))


def hashtags_in(text: str) -> list[str]:
    return [h.lower() for h in re.findall(r"#[\w]+", text or "", flags=re.UNICODE)]


def is_meaningful(tok_list: list[str]) -> bool:
    """n-грамма годится в термины: не начинается и не заканчивается стоп-словом, есть хотя бы одно слово длиннее 2 символов."""
    return bool(tok_list) and tok_list[0] not in STOP and tok_list[-1] not in STOP and any(len(t) > 2 for t in tok_list)


def ngrams(tok_list: list[str], n: int):
    for i in range(len(tok_list) - n + 1):
        yield tok_list[i:i + n]
