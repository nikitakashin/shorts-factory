# Мемные звуки: что под какой смысл

Библиотека: `~/Samples/Meme` (путь задаётся в `assets/sfx_kit.json`) — у автора 1000 mp3 с myinstants. В `_manifest.json` они идут
**в порядке популярности** (индекс 0–50 — то, что сейчас крутят тиктокеры: FAAAH, Apple Pay, Vine Boom…).
В kit библиотека называется `meme:`, файл указывается как `"meme:FAAAH.mp3"`. Имена ниже проверены на
диске. В manifest `?` и точка в конце заменены на `_`, поэтому всегда бери имя с диска (`ls`).

Короткие роли уже есть в `assets/sfx_kit.json`: fahh, wrong, pay, vineboom, boowomp, bruh, correct, nope,
huh, wow, yippee, emotional, dundun, cricket, camera, pipe, cash, sadviolin, flashbang, censor.
Остальное ставь прямо по имени: `"sound": "meme:Вот это поворот.mp3"`.

## Как ставить мем, чтобы было смешно, а не шумно
- **Мем — это реакция на слово**, ставь его ровно на слово (`at`), атака сама выровняется по `onset`.
- **Голосовые мемы** («FAAAH», «Вот это поворот», «emotional damage») перекрывают речь. Ставь их на
  конец фразы или в паузу, ограничивай `max_len`. Если важное слово идёт сразу после — сдвинь мем на него.
- **Не больше 4–6 мемов на минуту**, остальное — нейтральные вжухи и попы Boom One. Мем на каждом слове
  перестаёт быть шуткой.
- **Громкость** — по ощущению «реакция зрителя»: −1…−5 дБ к голосу. Vine Boom и взрывы режь сильнее,
  они плотные (`gain_db` −15). Проверяй замером, как в SKILL.md.
- **Мемы с чужой музыкой** (Bad to the Bone, Aero Chord, Funky Town, Rat Dance, фонк, песни) могут
  словить Content ID. Короткий кусок обычно проходит, но на монетизируемый ролик лучше без них.
- В библиотеке много мата и 18+ (пердёж, стоны и т.п.) — только если автор сам в таком стиле.

## По смыслу

| Ситуация | Звуки (файл) |
|---|---|
| **Факап, провал, «ну всё»** | `FAAAH.mp3` (№1 тренд), `Emotional Damage Meme.mp3`, `GTA V - Wasted.mp3`, `SpongeBob Fail.mp3` |
| **Неправильно / фейк / нет** | `Wrong Answer Buzzer.mp3`, `Windows XP Error.mp3`, `nope.avi.mp3`, `Неправильный ответ.mp3` |
| **Разочарование, «зря»** | `spongebob boowomp.mp3`, `Womp Womp Womp.mp3`, `Sad Violin (the meme one).mp3` |
| **Деньги, цена** | `Apple Pay.mp3` (тренд), `Cash registere sound.mp3`, `Money SoundFX.mp3`, `Перевод денег.mp3`, `Лям двести.mp3`, `банкомат мелстрой.mp3` |
| **Развязка, «бац»** | `VINE BOOM SOUND.mp3`, `Вот это поворот.mp3`, `dun dun dunnnnnnnn.mp3`, `OOOH MY GOD.mp3` |
| **Успех, нашёл, получилось** | `Correct Answer GameShow.mp3`, `YIPPEEEEEEEEEEEEEE.mp3`, `LETS GOOOOOO.mp3`, `Steam Achievement.mp3`, `Minecraft XP Sound.mp3` |
| **Недоумение, «чего?»** | `HUH_ Cat meme.mp3`, `Wait, What!_.mp3`, `так, погоди ка, что-то здесь не так.mp3`, `а да ну нафиг.mp3` |
| **Тупо / кринж** | `BRUH.mp3`, `Awkward cricket.mp3`, `Сверчки.mp3` |
| **Умный ход, флекс** | `1,000,000,000 IQ.mp3`, `Гений.mp3`, `Мастер , как вы добились такого уровня_.mp3`, `rizz sound effect.mp3`, `Mogged.mp3`, `Galaxy meme.mp3` |
| **Удивление, вау** | `Anime Wow.mp3`, `нихуя себе.mp3` (мат) |
| **Смех над ситуацией** | `Cat laughing at you.mp3`, `Кот смеётся.mp3`, `Rizzbot laugh.mp3` |
| **Удар, жёсткая реплика** | `Metal pipe clang.mp3`, `Bone Crack.mp3`, `Punch Sound.mp3`, `Doge bonk.mp3` |
| **Вспышка, озарение, скриншот** | `CS-GO Flashbang.mp3`, `Звук фотоаппарата.mp3` |
| **Саспенс, нагнетание** | `Popular Riser.mp3`, `CINEMATIC SUSPENSE RISER.mp3`, `Dexter meme.mp3`, `Za Warudo - Anime's Time Stop.mp3` |
| **Спустя время / перемотка** | `a few moments later sponge bob sfx fun.mp3`, `Speedrun music.mp3` (музыка) |
| **Телепорт, смена сцены** | `Goku teleport sound.mp3`, `Minecraft Enderman Teleport Sound.mp3`, `A-Train zoom.mp3`, `whoosh sfx.mp3` |
| **Падение, неудача телом** | `Cartoon Slip.mp3`, `Mario Jump.mp3` |
| **Тревога, «запрещено»** | `-999 Social Credit Siren.mp3` |
| **Уведомления** | `Discord Notification.mp3`, `iPhone Notification.mp3` |
| **Мат (вместо пика)** | `Censor Beep 1.mp3`, `Запикивание матов.mp3` |
| **Русские мемы-реплики** | `Вот это поворот.mp3`, `ОХ ЗРЯ Я ТУДА ПОЛЕЗ.mp3`, `Кажется я близок к разгадке.mp3`, `Минута пошла.mp3`, `Абонент временно недоступен.mp3`, `Яндекс такси.mp3` |
| **Фон-ирония (музыка)** | `Elevator Music Background.mp3`, `Rat dance Music.mp3`, `Bad to the Bone Meme.mp3` — риск Content ID |

Чего нет в таблице — ищи по manifest (он в порядке популярности):
```bash
python3 -c "import json;[print(i,x['name']) for i,x in enumerate(json.load(open('$HOME/Samples/Meme/_manifest.json'))['items']) if 'фейл' in x['name'].lower() or 'fail' in x['name'].lower()]"
uv run --script $S/sfx_scan.py ~/Samples/Meme "*Fail*"     # длина, атака, пик
```

## Пример: шортс «FL Studio 26 на Mac»
- ФАКАП ГОДА → `fahh`, ФЕЙК → `wrong`, 3500 ₽ → `pay`, ОНА ЕСТЬ → `vineboom` (вместо саб-бочки), ЗРЯ СНИМАЛ → `boowomp`.
- Склейки, попы на пояснительных стикерах, тиканье на b-roll, боинг в конце — Boom One.
- Автор одобрил именно такое разделение: **переходы — продакшн-звуки Boom One, смысловые акценты — мемы.**
